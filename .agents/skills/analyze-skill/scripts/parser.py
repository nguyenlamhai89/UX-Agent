"""
parser.py — Markdown report parsing logic for skill analysis reports.

Parses existing analysis report files to extract date columns and
criteria table data, enabling report updates without data loss.
"""

from __future__ import annotations

import re

from constants import CATEGORIES



def parse_existing_report(content: str) -> dict:
    """Parse an existing report to extract its structure and data.

    Args:
        content: The full markdown content of the existing report.

    Returns:
        Dict with:
        - 'dates' (list[str]): Existing date column headers.
        - 'tables' (dict[str, dict[str, list[str]]]): Keyed by category key,
          each value is a dict mapping criteria label to list of cell contents.
    """
    result = {
        "dates": [],
        "tables": {},
    }

    # Find all category sections and their tables
    # Pattern: ## <category_title>\n\n| Criteria | date1 | date2 | ...\n|---...
    section_pattern = re.compile(
        r"## (\d+\.\s+.+?)\n\n"
        r"(\|.+\|)\n"       # header row
        r"(\|[-|: ]+\|)\n"  # separator row
        r"((?:\|.+\|\n?)*)",  # data rows
        re.MULTILINE,
    )

    for match in section_pattern.finditer(content):
        section_title = match.group(1).strip()
        header_row = match.group(2).strip()
        data_rows_text = match.group(4).strip()

        # Find which category this section belongs to
        cat_key = _find_category_key(section_title)
        if cat_key is None:
            continue

        # Parse header to get existing dates
        headers = [h.strip() for h in header_row.split("|") if h.strip()]
        # headers[0] = "Criteria", headers[1:] = date columns
        dates = headers[1:]
        if not result["dates"]:
            result["dates"] = dates

        # Parse data rows
        rows = _parse_data_rows(data_rows_text)
        result["tables"][cat_key] = rows

    return result


def _find_category_key(section_title: str) -> str | None:
    """Find the category key that matches a section title.

    Args:
        section_title: The section title from the markdown report.

    Returns:
        The category key string, or None if no match found.
    """
    for cat in CATEGORIES:
        if cat["title"] == section_title:
            return cat["key"]
    return None


def _parse_data_rows(data_rows_text: str) -> dict:
    """Parse markdown table data rows into a dict of criteria -> cell values.

    Args:
        data_rows_text: Raw text of the data rows (no header/separator).

    Returns:
        Dict mapping criteria label (str) to list of cell content strings.
    """
    rows = {}
    for row_line in data_rows_text.split("\n"):
        row_line = row_line.strip()
        if not row_line:
            continue
        cells = [c.strip() for c in row_line.split("|") if c.strip()]
        if len(cells) >= 2:
            criteria_name = cells[0]
            row_data = cells[1:]
            rows[criteria_name] = row_data
    return rows
