"""
map_transcript.py

Merges all individual mapped-transcript-<audio_name>.md files into a single
combined mapped-transcript.md with all interviewee columns side-by-side.

Usage:
    python3 map_transcript.py <folder_path>
"""

import os
import sys
import re
import glob
import tempfile


def parse_markdown_table(filepath):
    """
    Parse a Markdown table from a file and return headers and rows.

    Returns:
        tuple: (headers: list[str], rows: list[list[str]])
    """
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    headers = []
    rows = []
    found_header = False

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue

        cells = [cell.strip() for cell in stripped.split("|")]
        # Remove empty first and last elements from split
        cells = cells[1:-1] if len(cells) > 2 else cells

        if not found_header:
            headers = cells
            found_header = True
        elif all(c.replace("-", "").replace(":", "").strip() == "" for c in cells):
            # Skip separator row (e.g., |---|---|---|)
            continue
        else:
            rows.append(cells)

    return headers, rows


def find_questionnaire(interview_dir):
    """Find the full-questionnaire.md file in the folder."""
    questionnaire_path = os.path.join(interview_dir, "full-questionnaire.md")
    if os.path.exists(questionnaire_path):
        return questionnaire_path
    return None


def find_mapped_transcripts(interview_dir):
    """
    Find all mapped-transcript-<audio_name>.md files in the folder.
    Excludes the combined mapped-transcript.md file.

    Returns:
        list[str]: Sorted list of file paths.
    """
    pattern = os.path.join(interview_dir, "mapped-transcript-*.md")
    files = glob.glob(pattern)
    # Exclude the combined file
    combined = os.path.join(interview_dir, "mapped-transcript.md")
    files = [f for f in files if os.path.abspath(f) != os.path.abspath(combined)]
    return sorted(files)


def extract_audio_name(filepath):
    """
    Extract the audio name from a mapped-transcript-<audio_name>.md filename.

    Example:
        mapped-transcript-HR_Leanbase.md -> HR_Leanbase
    """
    basename = os.path.basename(filepath)
    match = re.match(r"mapped-transcript-(.+)\.md$", basename)
    if match:
        return match.group(1)
    return None


def merge_mapped_transcripts(folder_path):
    """
    Merge all individual mapped-transcript-<audio_name>.md files into a
    combined mapped-transcript.md.

    Args:
        folder_path: Path to the root project folder containing the Interview folder.

    Returns:
        str: Path to the generated mapped-transcript.md file.

    Raises:
        FileNotFoundError: If full-questionnaire.md is not found.
        ValueError: If no mapped transcript files are found.
    """
    interview_dir = os.path.join(folder_path, "Interview")
    
    # Find questionnaire for base structure
    questionnaire_path = find_questionnaire(interview_dir)
    if not questionnaire_path:
        raise FileNotFoundError(
            "full-questionnaire.md not found in the specified Interview folder."
        )

    # Parse base questionnaire
    base_headers, base_rows = parse_markdown_table(questionnaire_path)
    num_base_cols = len(base_headers)
    num_rows = len(base_rows)

    # Find all individual mapped transcript files
    mapped_files = find_mapped_transcripts(interview_dir)
    if not mapped_files:
        raise ValueError(
            "No mapped-transcript-<audio_name>.md files found in the specified Interview folder."
        )

    # Collect interviewee columns
    interviewee_names = []
    interviewee_data = []  # list of lists, each inner list has num_rows entries

    for mapped_file in mapped_files:
        audio_name = extract_audio_name(mapped_file)
        if not audio_name:
            continue

        headers, rows = parse_markdown_table(mapped_file)

        # The interviewee column is the last column
        if len(headers) <= num_base_cols:
            continue

        # Use the header name from the markdown table itself instead of the filename
        # This handles short, readable aliases.
        interviewee_names.append(headers[-1])

        # Create mapping of base row keys to responses to handle potential row reordering
        def make_key(row_cells):
            padded = list(row_cells[:num_base_cols]) + [""] * max(0, num_base_cols - len(row_cells[:num_base_cols]))
            return tuple(" ".join(str(c).lower().split()) for c in padded)
            
        row_mapping = {}
        for r_idx, row in enumerate(rows):
            if len(row) > num_base_cols:
                key = make_key(row)
                response = row[-1]
                row_mapping[key] = (r_idx, response)

        # Extract the last column (interviewee responses) from each row
        column_data = []
        used_indices = set()
        for i in range(num_rows):
            base_row = base_rows[i]
            key = make_key(base_row)
            
            if key in row_mapping:
                r_idx, response = row_mapping[key]
                column_data.append(response)
                used_indices.add(r_idx)
            else:
                # Fallback to positional mapping if text was slightly modified but row order is maintained
                if i < len(rows) and len(rows[i]) > num_base_cols and i not in used_indices:
                    column_data.append(rows[i][-1])
                    used_indices.add(i)
                else:
                    column_data.append("N/A")

        interviewee_data.append(column_data)

    if not interviewee_names:
        raise ValueError(
            "No valid interviewee data could be extracted from the mapped transcript files."
        )

    # Build combined table
    combined_headers = base_headers + interviewee_names
    combined_rows = []

    for i in range(num_rows):
        row = list(base_rows[i]) if i < len(base_rows) else [""] * num_base_cols
        for col_data in interviewee_data:
            row.append(col_data[i] if i < len(col_data) else "N/A")
        combined_rows.append(row)

    # Generate Markdown output
    output_lines = ["# Mapped Transcript\n\n"]

    # Header row
    header_line = "| " + " | ".join(combined_headers) + " |"
    output_lines.append(header_line + "\n")

    # Separator row
    separator = "| " + " | ".join(["---"] * len(combined_headers)) + " |"
    output_lines.append(separator + "\n")

    # Data rows
    for row in combined_rows:
        row_line = "| " + " | ".join(row) + " |"
        output_lines.append(row_line + "\n")

    import shutil
    
    # Write output file atomically (write to temp, then rename)
    output_path = os.path.join(interview_dir, "mapped-transcript.md")
    fd, tmp_path = tempfile.mkstemp(
        suffix=".md", prefix=".mapped-transcript-tmp-", dir=interview_dir
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(output_lines)
        os.replace(tmp_path, output_path)
    except Exception:
        # Clean up temp file on failure
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    # Clean up temporary chunk directories
    try:
        chunk_dirs = glob.glob(os.path.join(interview_dir, ".chunks_*"))
        for chunk_dir in chunk_dirs:
            if os.path.isdir(chunk_dir):
                shutil.rmtree(chunk_dir)
    except Exception as e:
        print(f"Warning: Failed to clean up chunk directories: {e}")

    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 map_transcript.py <folder_path>")
        sys.exit(1)

    folder_path = sys.argv[1]

    if not os.path.isdir(folder_path):
        print(f"Error: '{folder_path}' is not a valid directory.")
        sys.exit(1)

    try:
        output_path = merge_mapped_transcripts(folder_path)
        print(f"Successfully created: {output_path}")
        print("DONE_MERGE")
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        sys.exit(1)
