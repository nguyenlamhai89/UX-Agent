import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.validate_questionnaire import parse_markdown_table, validate_questionnaire


SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "validate_questionnaire.py"


def write_questionnaire(tmp_path, body, name="full-questionnaire.md"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


VALID_TABLE = """# Questionnaire

| # | Theme | Question | Observed Variable |
|---|-------|----------|-------------------|
| 1 | Warm Up | Please introduce yourself | Name |
| 1 | Warm Up | Please introduce yourself | Age |
| 2 | Product | Bạn thấy ứng dụng thế nào? | Ease of use |
"""


def test_valid_table(tmp_path):
    assert validate_questionnaire(str(write_questionnaire(tmp_path, VALID_TABLE)))["status"] == "success"


@pytest.mark.parametrize(
    ("body", "error_code"),
    [
        ("", "NO_TABLE_FOUND"),
        (VALID_TABLE.replace("# Questionnaire", "# Notes", 1), "INVALID_DOCUMENT"),
        (VALID_TABLE.replace("| # | Theme | Question | Observed Variable |", "| # | Theme | Question |", 1), "INVALID_SEPARATOR"),
        (VALID_TABLE.replace("Observed Variable", "Variable", 1), "INVALID_HEADERS"),
        (VALID_TABLE + "Extra explanation", "INVALID_DOCUMENT"),
        (VALID_TABLE + "| # | Theme | Question | Observed Variable |\n|---|---|---|---|\n| 3 | X | Y | Z |", "DUPLICATE_TABLE"),
        (VALID_TABLE.replace("Ease of use", "Use<br>learnability", 1), "INVALID_CELL_CONTENT"),
        (VALID_TABLE.replace("| 2 | Product | Bạn thấy ứng dụng thế nào? | Ease of use |", "| 3 | Product | Bạn thấy ứng dụng thế nào? | Ease of use |", 1), "INVALID_NUMBERING"),
        (VALID_TABLE.replace("| 1 | Warm Up | Please introduce yourself | Age |", "| 2 | Warm Up | Please introduce yourself | Age |", 1), "INVALID_NUMBERING"),
        (VALID_TABLE.replace("| 1 | Warm Up | Please introduce yourself | Name |", "| 1 | Warm Up |  | Name |", 1), "EMPTY_QUESTION"),
        (VALID_TABLE.replace("| 1 | Warm Up | Please introduce yourself | Name |", "| 1 | Warm Up | Please introduce yourself |  |", 1), "EMPTY_VARIABLE"),
        (VALID_TABLE.replace("| 1 | Warm Up | Please introduce yourself | Name |", "| 1 | Warm Up | Please introduce yourself | Name | Extra |", 1), "MALFORMED_ROW"),
    ],
)
def test_rejects_invalid_documents(tmp_path, body, error_code):
    result = validate_questionnaire(str(write_questionnaire(tmp_path, body)))
    assert result["status"] == "error"
    assert result["error_code"] == error_code


def test_missing_file():
    assert validate_questionnaire("does-not-exist.md")["error_code"] == "FILE_NOT_FOUND"


def test_escaped_pipe_is_preserved(tmp_path):
    path = write_questionnaire(
        tmp_path,
        VALID_TABLE.replace("Ease of use", "Useful \\| easy to learn", 1),
    )
    headers, rows = parse_markdown_table(str(path))
    assert headers == ["#", "Theme", "Question", "Observed Variable"]
    assert rows[-1][-1] == "Useful | easy to learn"
    assert validate_questionnaire(str(path))["status"] == "success"


def test_cli_exit_codes(tmp_path):
    valid_path = write_questionnaire(tmp_path, VALID_TABLE)
    invalid_path = write_questionnaire(tmp_path, "# Questionnaire", "invalid.md")
    valid_result = subprocess.run([sys.executable, str(SCRIPT_PATH), str(valid_path)], capture_output=True, text=True, check=False)
    invalid_result = subprocess.run([sys.executable, str(SCRIPT_PATH), str(invalid_path)], capture_output=True, text=True, check=False)
    assert valid_result.returncode == 0
    assert '"status": "success"' in valid_result.stdout
    assert invalid_result.returncode == 1
    assert '"error_code": "NO_TABLE_FOUND"' in invalid_result.stdout
