"""
builder.py — Report construction logic for skill analysis reports.

Builds new reports from scratch or updates existing ones by appending
a new date column while preserving all prior data.
"""

from constants import CATEGORIES, DEFAULT_CRITERIA
from formatter import format_cell


def build_new_report(skill_name: str, date: str, analysis: dict) -> str:
    """Build a complete new analysis report from scratch.

    Args:
        skill_name: Name of the analyzed skill.
        date: Date string for the column header (YYYY-MM-DD).
        analysis: Full analysis dict structured by category.

    Returns:
        Complete markdown report string.
    """
    lines = []
    lines.append(f"# Skill Performance Analysis: {skill_name}")
    lines.append("")
    lines.append(f"> Last updated: {date}")
    lines.append("")

    for cat in CATEGORIES:
        lines.append("---")
        lines.append("")
        lines.append(f"## {cat['title']}")
        lines.append("")

        # Table header
        lines.append(f"| Criteria | {date} |")
        lines.append("|----------|----------|")

        # Table rows
        cat_data = analysis.get(cat["key"], {})
        for criteria_key, criteria_label in cat["criteria"]:
            criteria_data = cat_data.get(criteria_key, DEFAULT_CRITERIA.copy())
            cell = format_cell(criteria_data)
            lines.append(f"| {criteria_label} | {cell} |")

        lines.append("")

    return "\n".join(lines)


def update_existing_report(
    content: str, skill_name: str, date: str, analysis: dict,
    existing_data: dict,
) -> str:
    """Update an existing report by appending a new date column.

    Args:
        content: The original markdown content (unused but kept for signature
            compatibility — the report is rebuilt from existing_data).
        skill_name: Name of the analyzed skill.
        date: New date string for the column header.
        analysis: Full analysis dict structured by category.
        existing_data: Parsed data from parser.parse_existing_report().

    Returns:
        Updated markdown report string.
    """
    existing_dates = existing_data["dates"]
    all_dates = existing_dates + [date]

    lines = []
    lines.append(f"# Skill Performance Analysis: {skill_name}")
    lines.append("")
    lines.append(f"> Last updated: {date}")
    lines.append("")

    for cat in CATEGORIES:
        lines.append("---")
        lines.append("")
        lines.append(f"## {cat['title']}")
        lines.append("")

        # Table header with all dates
        date_headers = " | ".join(all_dates)
        separator_cells = " | ".join(["----------"] * len(all_dates))
        lines.append(f"| Criteria | {date_headers} |")
        lines.append(f"|----------|{separator_cells}|")

        # Table rows
        cat_data = analysis.get(cat["key"], {})
        existing_rows = existing_data["tables"].get(cat["key"], {})

        for criteria_key, criteria_label in cat["criteria"]:
            # Get existing cell data
            existing_cells = existing_rows.get(criteria_label, [])

            # Pad with N/A if needed (in case of missing data)
            while len(existing_cells) < len(existing_dates):
                existing_cells.append("N/A")

            # Build new cell
            criteria_data = cat_data.get(criteria_key, DEFAULT_CRITERIA.copy())
            new_cell = format_cell(criteria_data)

            # Combine all cells
            all_cells = existing_cells + [new_cell]
            cells_str = " | ".join(all_cells)
            lines.append(f"| {criteria_label} | {cells_str} |")

        lines.append("")

    return "\n".join(lines)
