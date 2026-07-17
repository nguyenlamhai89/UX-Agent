import os
import sys
import json
import pytest

# Add the parent directory to the path so we can import the script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from scripts.validate_questionnaire import validate_questionnaire, parse_markdown_table

@pytest.fixture
def valid_table_path(tmp_path):
    content = """
# Questionnaire

| # | Theme | Question | Observed Variable |
|---|-------|----------|-------------------|
| 1 | Warm Up | Please introduce yourself | Name |
| 1 | Warm Up | Please introduce yourself | Age |
| 2 | Warm Up | How was your day today | Journey |
| 3 | Product | What do you think | First Impression |
"""
    p = tmp_path / "full-questionnaire.md"
    p.write_text(content)
    return str(p)

@pytest.fixture
def missing_columns_path(tmp_path):
    content = """
| # | Theme | Question |
|---|-------|----------|
| 1 | Warm Up | Please introduce yourself |
"""
    p = tmp_path / "missing-cols.md"
    p.write_text(content)
    return str(p)

@pytest.fixture
def empty_mandatory_path(tmp_path):
    content = """
| # | Theme | Question | Observed Variable |
|---|-------|----------|-------------------|
| 1 | Warm Up |  | Name |
"""
    p = tmp_path / "empty-mandatory.md"
    p.write_text(content)
    return str(p)

@pytest.fixture
def invalid_numbering_path(tmp_path):
    content = """
| # | Theme | Question | Observed Variable |
|---|-------|----------|-------------------|
| 1 | Warm Up | Please introduce yourself | Name |
| 2 | Warm Up | Please introduce yourself | Age |
"""
    p = tmp_path / "invalid-numbering.md"
    p.write_text(content)
    return str(p)

@pytest.fixture
def invalid_start_number_path(tmp_path):
    content = """
| # | Theme | Question | Observed Variable |
|---|-------|----------|-------------------|
| 2 | Warm Up | Please introduce yourself | Name |
"""
    p = tmp_path / "invalid-start.md"
    p.write_text(content)
    return str(p)

@pytest.fixture
def skipped_number_path(tmp_path):
    content = """
| # | Theme | Question | Observed Variable |
|---|-------|----------|-------------------|
| 1 | Warm Up | Please introduce yourself | Name |
| 3 | Warm Up | How was your day today | Journey |
"""
    p = tmp_path / "skipped-number.md"
    p.write_text(content)
    return str(p)

@pytest.fixture
def malformed_row_path(tmp_path):
    content = """
| # | Theme | Question | Observed Variable |
|---|-------|----------|-------------------|
| 1 | Warm Up | Please introduce yourself | Name | Extra |
"""
    p = tmp_path / "malformed-row.md"
    p.write_text(content)
    return str(p)

def test_valid_table(valid_table_path):
    result = validate_questionnaire(valid_table_path)
    assert result["status"] == "success"

def test_missing_file():
    result = validate_questionnaire("does-not-exist.md")
    assert result["status"] == "error"
    assert result["error_code"] == "FILE_NOT_FOUND"

def test_missing_columns(missing_columns_path):
    result = validate_questionnaire(missing_columns_path)
    assert result["status"] == "error"
    assert result["error_code"] == "INVALID_COLUMNS"

def test_empty_mandatory(empty_mandatory_path):
    result = validate_questionnaire(empty_mandatory_path)
    assert result["status"] == "error"
    assert result["error_code"] == "EMPTY_QUESTION"

def test_invalid_numbering(invalid_numbering_path):
    result = validate_questionnaire(invalid_numbering_path)
    assert result["status"] == "error"
    assert result["error_code"] == "INVALID_NUMBERING"
    assert "same question but number changed" in result["message"]

def test_invalid_start_number(invalid_start_number_path):
    result = validate_questionnaire(invalid_start_number_path)
    assert result["status"] == "error"
    assert result["error_code"] == "INVALID_NUMBERING"
    assert "must start with # 1" in result["message"]

def test_skipped_number(skipped_number_path):
    result = validate_questionnaire(skipped_number_path)
    assert result["status"] == "error"
    assert result["error_code"] == "INVALID_NUMBERING"
    assert "expected # 2" in result["message"]

def test_malformed_row(malformed_row_path):
    result = validate_questionnaire(malformed_row_path)
    assert result["status"] == "error"
    assert result["error_code"] == "MALFORMED_ROW"
