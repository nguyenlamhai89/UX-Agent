import os
import sys
import json
import argparse
import re

def parse_markdown_table(file_path):
    """
    Parses a markdown table from a file.
    Returns (headers, rows).
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    headers = []
    rows = []
    in_table = False

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith('|') and line.endswith('|'):
            cells = [cell.strip() for cell in line.split('|')[1:-1]]
            
            # Check for separator row (e.g., |---|---|)
            if all(re.match(r'^:?-+:?$', cell) for cell in cells):
                in_table = True
                continue

            if not in_table:
                if not headers:
                    headers = cells
            else:
                rows.append(cells)

    if not headers and not rows:
        raise ValueError("No markdown table found in the file.")
        
    return headers, rows

def validate_questionnaire(file_path):
    try:
        headers, rows = parse_markdown_table(file_path)
    except FileNotFoundError:
        return {"status": "error", "error_code": "FILE_NOT_FOUND", "message": "full-questionnaire.md not found."}
    except ValueError as e:
        return {"status": "error", "error_code": "NO_TABLE_FOUND", "message": str(e)}

    # 1. Check column count and names
    expected_headers = ['#', 'Theme', 'Question', 'Observed Variable']
    if len(headers) != 4:
        return {"status": "error", "error_code": "INVALID_COLUMNS", "message": f"Expected 4 columns, found {len(headers)}."}
    
    # We allow slight variations in header names (case-insensitive), but structure must be exact.
    if [h.lower() for h in headers] != [h.lower() for h in expected_headers]:
         return {"status": "error", "error_code": "INVALID_HEADERS", "message": f"Expected headers {expected_headers}."}

    # 2. Check row contents and numbering logic
    if not rows:
        return {"status": "error", "error_code": "EMPTY_TABLE", "message": "The table has no data rows."}

    expected_number = 1
    previous_question = None

    for i, row in enumerate(rows):
        if len(row) != 4:
            return {"status": "error", "error_code": "MALFORMED_ROW", "message": f"Row {i+1} does not have exactly 4 columns."}

        num_str, theme, question, observed_var = row

        # Check for empty mandatory fields
        if not question:
            return {"status": "error", "error_code": "EMPTY_QUESTION", "message": f"Row {i+1} has an empty Question."}
        if not observed_var:
            return {"status": "error", "error_code": "EMPTY_VARIABLE", "message": f"Row {i+1} has an empty Observed Variable."}

        # Check numbering logic
        try:
            current_num = int(num_str)
        except ValueError:
            return {"status": "error", "error_code": "INVALID_NUMBERING", "message": f"Row {i+1} has non-integer # value: '{num_str}'"}

        if previous_question is None:
            # First row
            if current_num != expected_number:
                return {"status": "error", "error_code": "INVALID_NUMBERING", "message": f"Table must start with # 1, found {current_num}."}
        else:
            if question == previous_question:
                if current_num != expected_number:
                    return {"status": "error", "error_code": "INVALID_NUMBERING", "message": f"Row {i+1} has same question but number changed from {expected_number} to {current_num}."}
            else:
                expected_number += 1
                if current_num != expected_number:
                     return {"status": "error", "error_code": "INVALID_NUMBERING", "message": f"Row {i+1} question changed, expected # {expected_number} but found {current_num}."}

        previous_question = question

    return {"status": "success", "message": "Validation passed."}

def main():
    parser = argparse.ArgumentParser(description="Validate full-questionnaire.md")
    parser.add_argument("file_path", help="Path to full-questionnaire.md")
    args = parser.parse_args()

    result = validate_questionnaire(args.file_path)
    
    # Print JSON to stdout for orchestrator/AI to read
    print(json.dumps(result, ensure_ascii=False, indent=2))
    
    if result["status"] == "error":
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()
