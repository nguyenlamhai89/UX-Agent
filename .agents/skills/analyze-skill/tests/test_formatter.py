#!/usr/bin/env python3
"""
Unit tests for formatter.py — Cell formatting logic.
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

from formatter import format_cell


class TestFormatCell:
    """Tests for format_cell()."""

    def test_cell_basic(self):
        """Test that a cell formats score and analysis properly."""
        data = {
            "score": "5/10",
            "analysis": "Needs improvement.",
        }
        result = format_cell(data)

        assert result == "• **5/10** — Needs improvement. • No improvement needed."

    def test_cell_includes_solutions(self):
        """Test that recommendations are emitted in the required format."""
        data = {
            "score": "9/10",
            "analysis": "Excellent performance.",
            "solutions": ["Fix the issue."],
        }
        result = format_cell(data)

        assert result == "• **9/10** — Excellent performance. • **Solution**: Fix the issue."

    def test_cell_with_missing_fields(self):
        """Test that missing fields fall back to defaults."""
        result = format_cell({})

        assert result == "• **N/A** — No analysis available. • No improvement needed."

    def test_cell_with_partial_fields(self):
        """Test that partially provided fields work correctly."""
        data = {"score": "6/10"}
        result = format_cell(data)

        assert result == "• **6/10** — No analysis available. • No improvement needed."
