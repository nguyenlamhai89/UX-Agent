#!/usr/bin/env python3
"""
Unit tests for builder.py — Report construction logic.
"""

import os
import sys

import pytest

# Add the scripts directory to sys.path
SCRIPTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
)
sys.path.insert(0, SCRIPTS_DIR)

from builder import build_new_report, update_existing_report
from constants import CATEGORIES
from parser import parse_existing_report


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


class TestBuildNewReport:
    """Tests for build_new_report()."""

    def test_has_title(self):
        """Test that new report includes the skill name in the title."""
        analysis = _build_sample_analysis()
        report = build_new_report("my-skill", "2026-07-03", analysis)

        assert "# Skill Performance Analysis: my-skill" in report

    def test_has_last_updated(self):
        """Test that new report includes the last updated date."""
        analysis = _build_sample_analysis()
        report = build_new_report("my-skill", "2026-07-03", analysis)

        assert "> Last updated: 2026-07-03" in report

    def test_has_all_sections(self):
        """Test that new report contains all 5 category sections."""
        analysis = _build_sample_analysis()
        report = build_new_report("my-skill", "2026-07-03", analysis)

        for cat in CATEGORIES:
            assert f"## {cat['title']}" in report

    def test_has_correct_row_count(self):
        """Test that new report has 19 data rows (4+4+4+4+3)."""
        analysis = _build_sample_analysis()
        report = build_new_report("my-skill", "2026-07-03", analysis)

        data_rows = [
            line for line in report.split("\n")
            if line.strip().startswith("|")
            and not line.strip().startswith("| Criteria")
            and not line.strip().startswith("|---")
        ]
        assert len(data_rows) == 19

    def test_missing_category_uses_defaults(self):
        """Test that missing categories produce N/A values."""
        partial = {"execution_efficiency": _build_sample_analysis()["execution_efficiency"]}
        report = build_new_report("my-skill", "2026-07-03", partial)

        assert "• **N/A** — No data available." in report

    def test_has_score_and_analysis_format(self):
        """Test that cells contain only score and analysis, not solutions."""
        analysis = _build_sample_analysis()
        report = build_new_report("my-skill", "2026-07-03", analysis)

        assert "• **7/10**" in report
        assert "Solution" not in report
        assert "No improvement needed" not in report


class TestUpdateExistingReport:
    """Tests for update_existing_report()."""

    def test_adds_date_column(self):
        """Test that update appends a new date column header."""
        analysis1 = _build_sample_analysis("7")
        analysis2 = _build_sample_analysis("9")

        report1 = build_new_report("my-skill", "2026-07-03", analysis1)
        parsed = parse_existing_report(report1)
        report2 = update_existing_report(
            report1, "my-skill", "2026-07-10", analysis2, parsed,
        )

        assert "| Criteria | 2026-07-03 | 2026-07-10 |" in report2

    def test_preserves_original_scores(self):
        """Test that original scores are preserved after update."""
        analysis1 = _build_sample_analysis("5")
        analysis2 = _build_sample_analysis("9")

        report1 = build_new_report("my-skill", "2026-07-03", analysis1)
        parsed = parse_existing_report(report1)
        report2 = update_existing_report(
            report1, "my-skill", "2026-07-10", analysis2, parsed,
        )

        assert "• **5/10**" in report2
        assert "• **9/10**" in report2

    def test_changes_last_updated(self):
        """Test that last updated date reflects the latest analysis."""
        analysis = _build_sample_analysis()

        report1 = build_new_report("my-skill", "2026-07-03", analysis)
        parsed = parse_existing_report(report1)
        report2 = update_existing_report(
            report1, "my-skill", "2026-07-10", analysis, parsed,
        )

        assert "> Last updated: 2026-07-10" in report2
        assert "> Last updated: 2026-07-03" not in report2

    def test_three_sequential_updates(self):
        """Test that 3 sequential updates produce 3 date columns."""
        dates_and_scores = [("2026-07-01", "5"), ("2026-07-08", "7"), ("2026-07-15", "9")]

        report = None
        for date, score in dates_and_scores:
            analysis = _build_sample_analysis(score)
            if report is None:
                report = build_new_report("my-skill", date, analysis)
            else:
                parsed = parse_existing_report(report)
                report = update_existing_report(
                    report, "my-skill", date, analysis, parsed,
                )

        assert "| Criteria | 2026-07-01 | 2026-07-08 | 2026-07-15 |" in report
        assert "• **5/10**" in report
        assert "• **7/10**" in report
        assert "• **9/10**" in report
