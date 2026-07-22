import json
import os
import subprocess
import sys

from helpers import QUESTIONNAIRE_CONTENT, mapped_content, transcript_content

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "scripts"))

from validate_mapping import validate_mapping


def _files(tmp_path, mapped=None, questionnaire=QUESTIONNAIRE_CONTENT):
    questionnaire_path = tmp_path / "full-questionnaire.md"
    transcript_path = tmp_path / "transcript_user.md"
    mapped_path = tmp_path / "mapped-transcript-user.md"
    questionnaire_path.write_text(questionnaire, encoding="utf-8")
    transcript_path.write_text(transcript_content("User"), encoding="utf-8")
    mapped_path.write_text(mapped or mapped_content("User"), encoding="utf-8")
    return questionnaire_path, mapped_path, transcript_path


def _codes(result):
    return {issue.code for issue in result.issues}


def test_valid_mapping(tmp_path):
    questionnaire, mapped, transcript = _files(tmp_path)
    result = validate_mapping(str(questionnaire), str(mapped), str(transcript))
    assert result.valid
    assert result.total_rows == 4
    assert result.answered == 3
    assert result.not_applicable == 1


def test_wrong_header_is_rejected(tmp_path):
    questionnaire, mapped, transcript = _files(
        tmp_path,
        mapped=mapped_content("User").replace("Observed Variable", "Variable", 1),
    )
    result = validate_mapping(str(questionnaire), str(mapped), str(transcript))
    assert "INVALID_MAPPED_HEADER" in _codes(result)


def test_same_count_wrong_row_is_rejected(tmp_path):
    questionnaire, mapped, transcript = _files(
        tmp_path,
        mapped=mapped_content("User").replace("| 2 | Product |", "| 9 | Product |"),
    )
    result = validate_mapping(str(questionnaire), str(mapped), str(transcript))
    assert "ROW_IDENTITY_MISMATCH" in _codes(result)


def test_raw_pipe_is_rejected(tmp_path):
    content = mapped_content("User").replace("My name is User", "A | B")
    questionnaire, mapped, transcript = _files(tmp_path, mapped=content)
    result = validate_mapping(str(questionnaire), str(mapped), str(transcript))
    assert "MALFORMED_MAPPED_ROW" in _codes(result)


def test_html_pipe_entity_is_accepted(tmp_path):
    content = mapped_content("User").replace("My name is User", "A &#124; B")
    questionnaire, mapped, transcript = _files(tmp_path, mapped=content)
    assert validate_mapping(str(questionnaire), str(mapped), str(transcript)).valid


def test_missing_summary_is_rejected(tmp_path):
    content = mapped_content("User").split("> **Mapping Summary**:")[0]
    questionnaire, mapped, transcript = _files(tmp_path, mapped=content)
    result = validate_mapping(str(questionnaire), str(mapped), str(transcript))
    assert "INVALID_MAPPING_SUMMARY" in _codes(result)


def test_summary_counts_are_rejected(tmp_path):
    questionnaire, mapped, transcript = _files(
        tmp_path,
        mapped=mapped_content("User", summary_total=99),
    )
    result = validate_mapping(str(questionnaire), str(mapped), str(transcript))
    assert "SUMMARY_COUNT_MISMATCH" in _codes(result)


def test_coverage_is_rejected(tmp_path):
    questionnaire, mapped, transcript = _files(
        tmp_path,
        mapped=mapped_content("User", coverage_end="[01:10]"),
    )
    result = validate_mapping(str(questionnaire), str(mapped), str(transcript))
    assert "COVERAGE_MISMATCH" in _codes(result)


def test_answer_requires_timestamp_and_highlight(tmp_path):
    response = "Plain response"
    questionnaire, mapped, transcript = _files(
        tmp_path,
        mapped=mapped_content("User", first_response=response),
    )
    result = validate_mapping(str(questionnaire), str(mapped), str(transcript))
    assert {"MISSING_RESPONSE_TIMESTAMP", "MISSING_CORE_HIGHLIGHT"} <= _codes(result)


def test_source_without_timestamps_is_rejected(tmp_path):
    questionnaire, mapped, transcript = _files(tmp_path)
    transcript.write_text("Transcript without timestamps", encoding="utf-8")
    result = validate_mapping(str(questionnaire), str(mapped), str(transcript))
    assert "NO_TRANSCRIPT_TIMESTAMPS" in _codes(result)


def test_cli_json_contract(tmp_path):
    questionnaire, mapped, transcript = _files(tmp_path)
    script = os.path.join(
        os.path.dirname(__file__), "..", "scripts", "validate_mapping.py"
    )
    completed = subprocess.run(
        [
            sys.executable,
            script,
            str(questionnaire),
            str(mapped),
            "--transcript",
            str(transcript),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert json.loads(completed.stdout)["valid"] is True
