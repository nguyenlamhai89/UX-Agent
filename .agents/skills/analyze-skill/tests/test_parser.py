#!/usr/bin/env python3
"""
Unit tests for parser.py — Markdown report parsing logic.
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


class TestParseExistingReport:
    """Tests for parse_existing_report()."""

    def test_parses_single_date_report(self):
        """Test parsing a report with one date column."""
        analysis = _build_sample_analysis()
        report = build_new_report("test-skill", "2026-07-03", analysis)

        parsed = parse_existing_report(report)

        assert parsed["dates"] == ["2026-07-03"]
        assert len(parsed["tables"]) == 5

    def test_parses_all_category_tables(self):
        """Test that all 5 category tables are parsed."""
        analysis = _build_sample_analysis()
        report = build_new_report("test-skill", "2026-07-03", analysis)

        parsed = parse_existing_report(report)

        expected_keys = {cat["key"] for cat in CATEGORIES}
        assert set(parsed["tables"].keys()) == expected_keys

    def test_parses_criteria_rows(self):
        """Test that criteria rows are correctly parsed from tables."""
        analysis = _build_sample_analysis()
        report = build_new_report("test-skill", "2026-07-03", analysis)

        parsed = parse_existing_report(report)

        ee_rows = parsed["tables"]["execution_efficiency"]
        assert "Execution Time" in ee_rows
        assert "API Call Count" in ee_rows
        assert "Token Usage" in ee_rows
        assert "Resource Consumption" in ee_rows

    def test_parses_multi_date_report(self):
        """Test parsing a report that was updated with multiple dates."""
        analysis1 = _build_sample_analysis("6")
        analysis2 = _build_sample_analysis("8")

        report1 = build_new_report("test-skill", "2026-07-01", analysis1)
        parsed1 = parse_existing_report(report1)
        report2 = update_existing_report(
            report1, "test-skill", "2026-07-08", analysis2, parsed1,
        )

        parsed2 = parse_existing_report(report2)

        assert parsed2["dates"] == ["2026-07-01", "2026-07-08"]
        ee_rows = parsed2["tables"]["execution_efficiency"]
        assert len(ee_rows["Execution Time"]) == 2

    def test_parses_empty_content(self):
        """Test that empty content returns empty structure."""
        parsed = parse_existing_report("")

        assert parsed["dates"] == []
        assert parsed["tables"] == {}
