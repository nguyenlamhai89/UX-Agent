#!/usr/bin/env python3
"""
manage_report.py — CLI entry point for creating or updating skill analysis reports.

This is a thin CLI wrapper that delegates to the modular components:
- constants.py  — Category and criteria definitions
- formatter.py  — Cell formatting (2 bullet points: analysis + solution)
- parser.py     — Markdown report parsing
- builder.py    — Report construction (new + update)

Usage:
    python3 manage_report.py \
        --skill-name "map-transcript" \
        --date "2026-07-03" \
        --analysis-json '<JSON string>' \
        --output-dir ".agents/workflows/ux-transcribe/Analysis"
"""

import argparse
import json
import os
import sys

from builder import build_new_report, update_existing_report
from constants import CATEGORIES
from parser import parse_existing_report


def main():
    """Main entry point for the report management script."""
    parser = argparse.ArgumentParser(
        description="Create or update a skill performance analysis report.",
    )
    parser.add_argument(
        "--skill-name",
        required=True,
        help="Name of the skill being analyzed.",
    )
    parser.add_argument(
        "--date",
        required=True,
        help="Date string for the column header (YYYY-MM-DD).",
    )
    analysis_source = parser.add_mutually_exclusive_group(required=True)
    analysis_source.add_argument(
        "--analysis-json",
        help="JSON string containing the analysis data.",
    )
    analysis_source.add_argument(
        "--analysis-json-file",
        help="Path to a UTF-8 JSON file containing the analysis data.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Path to the Analysis/ output directory.",
    )

    args = parser.parse_args()

    # Read and parse the analysis JSON. A file input avoids shell-quoting
    # failures for long reports with punctuation-heavy analysis text.
    analysis_json = args.analysis_json
    if args.analysis_json_file:
        try:
            with open(args.analysis_json_file, "r", encoding="utf-8") as f:
                analysis_json = f.read()
        except OSError as e:
            print(
                f"ERROR: Could not read --analysis-json-file: {e}",
                file=sys.stderr,
            )
            sys.exit(1)

    try:
        analysis = json.loads(analysis_json)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in --analysis-json: {e}", file=sys.stderr)
        sys.exit(1)

    # Validate required category keys
    required_keys = [cat["key"] for cat in CATEGORIES]
    missing_keys = [k for k in required_keys if k not in analysis]
    if missing_keys:
        print(
            f"WARNING: Missing category keys in analysis JSON: {missing_keys}. "
            "They will be filled with N/A values.",
            file=sys.stderr,
        )

    # Create output directory if needed
    os.makedirs(args.output_dir, exist_ok=True)

    # Determine report file path
    report_filename = f"analysis-{args.skill_name}.md"
    report_path = os.path.join(args.output_dir, report_filename)

    # Create or update
    if os.path.exists(report_path):
        with open(report_path, "r", encoding="utf-8") as f:
            existing_content = f.read()

        existing_data = parse_existing_report(existing_content)

        # Check if this date already exists
        if args.date in existing_data["dates"]:
            print(
                f"WARNING: Date '{args.date}' already exists in the report. "
                "A new column will still be appended with the updated analysis.",
                file=sys.stderr,
            )

        report_content = update_existing_report(
            existing_content, args.skill_name, args.date, analysis,
            existing_data,
        )
        action = "Updated"
    else:
        report_content = build_new_report(args.skill_name, args.date, analysis)
        action = "Created"

    # Write the report
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report_content)

    print(f"{action} report: {os.path.abspath(report_path)}")


if __name__ == "__main__":
    main()
