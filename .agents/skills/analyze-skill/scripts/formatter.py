"""
formatter.py — Cell formatting logic for skill analysis reports.

Formats individual criteria analysis data into the required two-bullet table
cell format: score/analysis plus a solution or explicit no-action statement.
"""


def format_cell(criteria_data: dict) -> str:
    """Format a single criteria analysis into a table cell.

    Args:
        criteria_data: Dict with 'score' and 'analysis' keys.

    Returns:
        Formatted cell string with score and analysis.
    """
    score = criteria_data.get("score", "N/A")
    analysis = criteria_data.get("analysis", "No analysis available.")

    # Build the required analysis and solution bullets.
    cell = f"• **{score}** — {analysis}"
    solutions = criteria_data.get("solutions") or []
    if solutions:
        cell += f" • **Solution**: {' '.join(solutions)}"
    else:
        cell += " • No improvement needed."

    return cell
