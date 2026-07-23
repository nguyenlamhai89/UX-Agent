#!/usr/bin/env python3
"""Validate the canonical ``full-questionnaire.md`` document format."""

import argparse
import json
import os
import re
import sys


EXPECTED_HEADERS = ["#", "Theme", "Question", "Observed Variable"]
HEADING = "# Questionnaire"
SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")


class QuestionnaireFormatError(ValueError):
    """A Markdown-format error with an actionable validator error code."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def split_markdown_row(line: str) -> list[str]:
    """Split one pipe-delimited row while preserving escaped literal pipes."""
    if not (line.startswith("|") and line.endswith("|")):
        raise QuestionnaireFormatError(
            "INVALID_DOCUMENT", "Every table row must start and end with a pipe.")

    cells: list[str] = []
    current: list[str] = []
    escaped = False

    for character in line[1:-1]:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)

    if escaped:
        current.append("\\")
    cells.append("".join(current).strip())
    return cells


def parse_markdown_table(file_path: str) -> tuple[list[str], list[list[str]]]:
    """Parse exactly one canonical questionnaire heading and table block."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as file:
        lines = [line.strip() for line in file if line.strip()]

    if not lines:
        raise QuestionnaireFormatError("NO_TABLE_FOUND", "No Markdown table found in the file.")
    if lines[0] != HEADING:
        raise QuestionnaireFormatError(
            "INVALID_DOCUMENT", f"The first non-empty line must be '{HEADING}'.")
    if len(lines) < 4:
        raise QuestionnaireFormatError(
            "NO_TABLE_FOUND", "The document must contain a heading, table header, separator, and data row.")
    if any(line.startswith("```") for line in lines):
        raise QuestionnaireFormatError("INVALID_DOCUMENT", "Code fences are not allowed.")

    headers = split_markdown_row(lines[1])
    separator = split_markdown_row(lines[2])
    if len(separator) != len(headers) or not all(
        SEPARATOR_CELL_RE.fullmatch(cell) for cell in separator
    ):
        raise QuestionnaireFormatError(
            "INVALID_SEPARATOR", "The header must be followed by a valid Markdown separator row.")

    rows = []
    for line in lines[3:]:
        row = split_markdown_row(line)
        if row == headers or (len(row) == len(headers) and all(SEPARATOR_CELL_RE.fullmatch(cell) for cell in row)):
            raise QuestionnaireFormatError("DUPLICATE_TABLE", "Only one questionnaire table is allowed.")
        rows.append(row)
    return headers, rows


def validate_questionnaire(file_path: str) -> dict[str, str]:
    """Validate one questionnaire file and return a stable JSON-ready result."""
    try:
        headers, rows = parse_markdown_table(file_path)
    except FileNotFoundError:
        return {"status": "error", "error_code": "FILE_NOT_FOUND", "message": "full-questionnaire.md not found."}
    except QuestionnaireFormatError as error:
        return {"status": "error", "error_code": error.error_code, "message": str(error)}
    except OSError as error:
        return {"status": "error", "error_code": "READ_FAILURE", "message": f"Could not read file: {error}"}

    if len(headers) != 4:
        return {"status": "error", "error_code": "INVALID_COLUMNS", "message": f"Expected 4 columns, found {len(headers)}."}
    if [header.lower() for header in headers] != [header.lower() for header in EXPECTED_HEADERS]:
        return {"status": "error", "error_code": "INVALID_HEADERS", "message": f"Expected headers {EXPECTED_HEADERS}."}
    if not rows:
        return {"status": "error", "error_code": "EMPTY_TABLE", "message": "The table has no data rows."}

    expected_number = 1
    previous_question = None
    for index, row in enumerate(rows, start=1):
        if len(row) != 4:
            return {"status": "error", "error_code": "MALFORMED_ROW", "message": f"Row {index} does not have exactly 4 columns."}

        number, _theme, question, observed_variable = row
        if any("<br" in cell.lower() for cell in row):
            return {"status": "error", "error_code": "INVALID_CELL_CONTENT", "message": f"Row {index} contains an HTML break tag."}
        if not question:
            return {"status": "error", "error_code": "EMPTY_QUESTION", "message": f"Row {index} has an empty Question."}
        if not observed_variable:
            return {"status": "error", "error_code": "EMPTY_VARIABLE", "message": f"Row {index} has an empty Observed Variable."}

        try:
            current_number = int(number)
        except ValueError:
            return {"status": "error", "error_code": "INVALID_NUMBERING", "message": f"Row {index} has non-integer # value: '{number}'"}

        if previous_question is None and current_number != expected_number:
            return {"status": "error", "error_code": "INVALID_NUMBERING", "message": f"Table must start with # 1, found {current_number}."}
        if previous_question is not None:
            if question == previous_question and current_number != expected_number:
                return {"status": "error", "error_code": "INVALID_NUMBERING", "message": f"Row {index} has same question but number changed from {expected_number} to {current_number}."}
            if question != previous_question:
                expected_number += 1
                if current_number != expected_number:
                    return {"status": "error", "error_code": "INVALID_NUMBERING", "message": f"Row {index} question changed, expected # {expected_number} but found {current_number}."}
        previous_question = question

    return {"status": "success", "message": "Validation passed."}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate full-questionnaire.md")
    parser.add_argument("file_path", help="Path to full-questionnaire.md")
    args = parser.parse_args()
    result = validate_questionnaire(args.file_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result["status"] == "success" else 1)


if __name__ == "__main__":
    main()
