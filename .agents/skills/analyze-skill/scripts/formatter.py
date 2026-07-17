"""
formatter.py — Cell formatting logic for skill analysis reports.

Formats individual criteria analysis data into the table cell format: 
• **score** — analysis.
(Solutions are added manually later upon user approval).
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

    # Build the analysis bullet point
    cell = f"• **{score}** — {analysis}"

    return cell
