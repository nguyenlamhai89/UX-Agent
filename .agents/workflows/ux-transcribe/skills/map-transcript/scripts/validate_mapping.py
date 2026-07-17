#!/usr/bin/env python3
"""
validate_mapping.py

Validates that a generated mapped-transcript-<audio_name>.md file
has exactly the same number of data rows as the original full-questionnaire.md.
Provides programmatic validation so the AI does not have to count rows manually.

Usage:
    python3 validate_mapping.py <questionnaire_path> <mapped_file_path>
"""

import os
import sys

def parse_markdown_table(filepath):
    if not os.path.exists(filepath):
        return []
        
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    rows = []
    found_header = False

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue

        cells = [cell.strip() for cell in stripped.split("|")]
        cells = cells[1:-1] if len(cells) > 2 else cells

        if not found_header:
            found_header = True
        elif all(c.replace("-", "").replace(":", "").strip() == "" for c in cells):
            continue
        else:
            rows.append(cells)

    return rows

def main():
    if len(sys.argv) != 3:
        print("Usage: python3 validate_mapping.py <questionnaire_path> <mapped_file_path>")
        sys.exit(1)

    questionnaire_path = sys.argv[1]
    mapped_file_path = sys.argv[2]

    base_rows = parse_markdown_table(questionnaire_path)
    if not base_rows:
        print(f"VALIDATION_FAILED: Cannot read questionnaire or it is empty.")
        sys.exit(1)

    mapped_rows = parse_markdown_table(mapped_file_path)
    if not mapped_rows:
        print(f"VALIDATION_FAILED: Cannot read mapped file or it is empty.")
        sys.exit(1)

    if len(base_rows) != len(mapped_rows):
        print(f"VALIDATION_FAILED: Expected {len(base_rows)} rows, but got {len(mapped_rows)} rows. You must retry the mapping to ensure no data is dropped.")
        sys.exit(1)

    print("VALIDATION_PASSED: The row count matches perfectly.")
    sys.exit(0)

if __name__ == "__main__":
    main()
