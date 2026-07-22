#!/usr/bin/env python3
"""
Integration tests for manage_report.py — CLI entry point.

Tests the full end-to-end workflow by running manage_report.py as a subprocess.
Unit tests for individual modules live in their own test files:
- test_formatter.py
- test_parser.py
- test_builder.py
"""

import json
import os
import subprocess
import sys

import pytest

# Path to the CLI entry point
SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
)
SCRIPT_PATH = os.path.join(SCRIPTS_DIR, "manage_report.py")


def _build_sample_analysis(score_prefix="7"):
    """Build a complete sample analysis JSON with all required keys."""
    def make_criteria(name, score=None):
        s = score or f"{score_prefix}/10"
        return {
            "score": s,
            "analysis": f"Analysis for {name}.",
            "solutions": [f"Solution for {name}."] if int(s.split("/")[0]) < 8 else [],
        }

    return {
        "execution_efficiency": {
            "execution_time": make_criteria("execution_time"),
            "api_call_count": make_criteria("api_call_count"),
            "token_usage": make_criteria("token_usage"),
            "resource_consumption": make_criteria("resource_consumption"),
        },
        "output_quality": {
            "output_completeness": make_criteria("output_completeness", "8/10"),
            "format_compliance": make_criteria("format_compliance"),
            "content_accuracy": make_criteria("content_accuracy", "9/10"),
            "human_approval_rate": make_criteria("human_approval_rate"),
        },
        "workflow_fit": {
            "io_contract_adherence": make_criteria("io_contract_adherence", "9/10"),
            "skip_logic_compatibility": make_criteria("skip_logic_compatibility", "8/10"),
            "pipeline_passthrough_rate": make_criteria("pipeline_passthrough_rate"),
            "idempotency": make_criteria("idempotency", "8/10"),
        },
        "reliability": {
            "error_rate": make_criteria("error_rate"),
            "error_recoverability": make_criteria("error_recoverability"),
            "retry_success_rate": make_criteria("retry_success_rate", "8/10"),
            "known_bug_recurrence": make_criteria("known_bug_recurrence"),
        },
        "cost_scalability": {
            "cost_per_execution": make_criteria("cost_per_execution", "5/10"),
            "scaling_behavior": make_criteria("scaling_behavior", "6/10"),
            "unit_test_coverage": make_criteria("unit_test_coverage"),
        },
    }


def run_script(skill_name, date, analysis_json_str, output_dir):
    """Run the manage_report.py script as a subprocess."""
    result = subprocess.run(
        [
            sys.executable, SCRIPT_PATH,
            "--skill-name", skill_name,
            "--date", date,
            "--analysis-json", analysis_json_str,
            "--output-dir", output_dir,
        ],
        capture_output=True,
        text=True,
    )
    return result


def run_script_file(skill_name, date, analysis_json_file, output_dir):
    """Run the CLI with a JSON file to avoid shell-quoting large payloads."""
    return subprocess.run(
        [
            sys.executable, SCRIPT_PATH,
            "--skill-name", skill_name,
            "--date", date,
            "--analysis-json-file", analysis_json_file,
            "--output-dir", output_dir,
        ],
        capture_output=True,
        text=True,
    )


class TestCLIIntegration:
    """End-to-end tests running manage_report.py as a subprocess."""

    def test_creates_analysis_folder(self, tmp_path):
        """Test that the Analysis/ folder is created if it doesn't exist."""
        output_dir = os.path.join(str(tmp_path), "Analysis")
        analysis = _build_sample_analysis()

        result = run_script(
            "map-transcript", "2026-07-03",
            json.dumps(analysis), output_dir,
        )

        assert result.returncode == 0
        assert os.path.isdir(output_dir)

    def test_creates_report_file(self, tmp_path):
        """Test that the report file is created with the correct name."""
        output_dir = str(tmp_path)
        analysis = _build_sample_analysis()

        run_script(
            "map-transcript", "2026-07-03",
            json.dumps(analysis), output_dir,
        )

        report_path = os.path.join(output_dir, "analysis-map-transcript.md")
        assert os.path.isfile(report_path)

    def test_report_has_all_5_sections(self, tmp_path):
        """Test that the CLI-generated report contains all 5 sections."""
        output_dir = str(tmp_path)
        analysis = _build_sample_analysis()

        run_script("my-skill", "2026-07-03", json.dumps(analysis), output_dir)

        report_path = os.path.join(output_dir, "analysis-my-skill.md")
        with open(report_path, "r") as f:
            content = f.read()

        assert "## 1. ⚡ Execution Efficiency" in content
        assert "## 2. 🎯 Output Quality & Accuracy" in content
        assert "## 3. 🔗 Workflow Fit" in content
        assert "## 4. 🛡️ Reliability & Error Handling" in content
        assert "## 5. 💰 Cost & Scalability" in content

    def test_cli_appends_new_date_column(self, tmp_path):
        """Test that running CLI twice appends a new date column."""
        output_dir = str(tmp_path)
        analysis1 = _build_sample_analysis("7")
        analysis2 = _build_sample_analysis("8")

        run_script("my-skill", "2026-07-03", json.dumps(analysis1), output_dir)
        result = run_script("my-skill", "2026-07-10", json.dumps(analysis2), output_dir)

        assert result.returncode == 0

        report_path = os.path.join(output_dir, "analysis-my-skill.md")
        with open(report_path, "r") as f:
            content = f.read()

        assert "| Criteria | 2026-07-03 | 2026-07-10 |" in content

    def test_invalid_json_exits_with_error(self, tmp_path):
        """Test that invalid JSON causes a non-zero exit code."""
        output_dir = str(tmp_path)

        result = run_script(
            "map-transcript", "2026-07-03",
            "not valid json{{{", output_dir,
        )

        assert result.returncode != 0
        assert "Invalid JSON" in result.stderr

    def test_accepts_analysis_json_file(self, tmp_path):
        """Long analysis payloads can be read from a UTF-8 JSON file."""
        output_dir = str(tmp_path / "reports")
        analysis_path = tmp_path / "analysis.json"
        analysis_path.write_text(
            json.dumps(_build_sample_analysis(), ensure_ascii=False),
            encoding="utf-8",
        )

        result = run_script_file(
            "visualize-insights",
            "2026-07-22",
            str(analysis_path),
            output_dir,
        )

        assert result.returncode == 0
        assert os.path.isfile(
            os.path.join(output_dir, "analysis-visualize-insights.md")
        )

    def test_missing_criteria_fills_with_na(self, tmp_path):
        """Test that missing criteria keys in the JSON produce N/A values."""
        output_dir = str(tmp_path)

        partial_analysis = {
            "execution_efficiency": {
                "execution_time": {
                    "score": "8/10",
                    "analysis": "Good performance.",
                    "solutions": [],
                },
            },
        }

        result = run_script(
            "map-transcript", "2026-07-03",
            json.dumps(partial_analysis), output_dir,
        )

        assert result.returncode == 0

        report_path = os.path.join(output_dir, "analysis-map-transcript.md")
        with open(report_path, "r") as f:
            content = f.read()

        assert "• **8/10** — Good performance." in content
        assert "• **N/A** — No data available." in content

    def test_different_skills_get_separate_reports(self, tmp_path):
        """Test that different skill names produce separate report files."""
        output_dir = str(tmp_path)
        analysis = _build_sample_analysis()

        run_script("skill-a", "2026-07-03", json.dumps(analysis), output_dir)
        run_script("skill-b", "2026-07-03", json.dumps(analysis), output_dir)

        assert os.path.isfile(os.path.join(output_dir, "analysis-skill-a.md"))
        assert os.path.isfile(os.path.join(output_dir, "analysis-skill-b.md"))
