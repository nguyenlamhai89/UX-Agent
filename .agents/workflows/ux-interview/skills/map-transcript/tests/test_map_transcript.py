import os
import sys

import pytest

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "scripts"))

from map_transcript import (
    PartialMappingError,
    extract_audio_name,
    find_mapped_transcripts,
    find_questionnaire,
    merge_mapping_outputs,
    merge_mapped_transcripts,
    parse_markdown_table,
)
from helpers import QUESTIONNAIRE_CONTENT, create_study, mapped_content, write_mapped


@pytest.fixture
def sample_folder(tmp_path):
    interview = create_study(tmp_path, count=2)
    write_mapped(interview, "user01", "User 1")
    write_mapped(interview, "user02", "User 2")
    return tmp_path


def test_parse_markdown_table_preserves_headers_and_rows(tmp_path):
    path = tmp_path / "questionnaire.md"
    path.write_text(QUESTIONNAIRE_CONTENT, encoding="utf-8")
    headers, rows = parse_markdown_table(str(path))
    assert headers == ["#", "Theme", "Question", "Observed Variable"]
    assert len(rows) == 4


def test_find_questionnaire(sample_folder):
    result = find_questionnaire(str(sample_folder / "Interview"))
    assert result and result.endswith("full-questionnaire.md")


def test_find_questionnaire_missing(tmp_path):
    assert find_questionnaire(str(tmp_path)) is None


def test_find_mapped_transcripts_excludes_generated_views(sample_folder):
    interview = sample_folder / "Interview"
    (interview / "mapped-transcript-review-01.md").write_text("review")
    (interview / "mapped-transcript.partial.md").write_text("partial")
    results = [
        os.path.basename(path) for path in find_mapped_transcripts(str(interview))
    ]
    assert results == ["mapped-transcript-user01.md", "mapped-transcript-user02.md"]


def test_extract_audio_name():
    assert extract_audio_name("mapped-transcript-user01.md") == "user01"
    assert extract_audio_name("mapped-transcript-review-01.md") is None
    assert extract_audio_name("mapped-transcript.md") is None


def test_strict_merge_generates_combined_review_batches_and_manifest(sample_folder):
    result = merge_mapping_outputs(str(sample_folder), review_batch_size=1)
    assert result["status"] == "success"
    assert result["total_expected"] == 2
    assert result["total_mapped"] == 2
    assert len(result["review_files"]) == 2
    assert os.path.exists(result["review_manifest"])
    headers, rows = parse_markdown_table(result["combined_file"])
    assert headers == [
        "#",
        "Theme",
        "Question",
        "Observed Variable",
        "User 1",
        "User 2",
    ]
    assert len(rows) == 4


def test_backward_compatible_merge_returns_canonical_path(sample_folder):
    output = merge_mapped_transcripts(str(sample_folder))
    assert output.endswith("mapped-transcript.md")
    assert os.path.isfile(output)


def test_merge_fails_closed_when_expected_user_is_missing(sample_folder):
    interview = sample_folder / "Interview"
    (interview / "mapped-transcript-user02.md").unlink()
    with pytest.raises(PartialMappingError) as exc:
        merge_mapping_outputs(str(sample_folder))
    assert exc.value.failures[0]["code"] == "MISSING_MAPPED_FILE"


def test_partial_merge_never_overwrites_canonical(sample_folder):
    interview = sample_folder / "Interview"
    canonical = interview / "mapped-transcript.md"
    canonical.write_text("last known good", encoding="utf-8")
    (interview / "mapped-transcript-user02.md").unlink()
    result = merge_mapping_outputs(str(sample_folder), allow_partial=True)
    assert result["status"] == "partial"
    assert result["combined_file"].endswith("mapped-transcript.partial.md")
    assert result["review_files"][0].endswith("mapped-transcript-partial-review-01.md")
    assert result["review_manifest"].endswith("mapping-review-manifest.partial.md")
    assert canonical.read_text(encoding="utf-8") == "last known good"


def test_merge_rejects_duplicate_aliases(sample_folder):
    interview = sample_folder / "Interview"
    (interview / "mapped-transcript-user02.md").write_text(
        mapped_content("User 1", source_alias="user02"),
        encoding="utf-8",
    )
    with pytest.raises(PartialMappingError) as exc:
        merge_mapping_outputs(str(sample_folder))
    assert exc.value.failures[0]["code"] == "DUPLICATE_ALIAS"


def test_merge_rejects_case_insensitive_duplicate_aliases(sample_folder):
    interview = sample_folder / "Interview"
    (interview / "mapped-transcript-user02.md").write_text(
        mapped_content("user 1", source_alias="user02"),
        encoding="utf-8",
    )
    with pytest.raises(PartialMappingError) as exc:
        merge_mapping_outputs(str(sample_folder))
    assert exc.value.failures[0]["code"] == "DUPLICATE_ALIAS"


def test_merge_rejects_same_count_wrong_row_identity(sample_folder):
    interview = sample_folder / "Interview"
    path = interview / "mapped-transcript-user02.md"
    content = path.read_text(encoding="utf-8").replace(
        "| 2 | Product |",
        "| 999 | Product |",
    )
    path.write_text(content, encoding="utf-8")
    with pytest.raises(PartialMappingError) as exc:
        merge_mapping_outputs(str(sample_folder))
    assert "ROW_IDENTITY_MISMATCH" in exc.value.failures[0]["issues"]


def test_merge_rejects_raw_pipe_in_response(sample_folder):
    interview = sample_folder / "Interview"
    path = interview / "mapped-transcript-user02.md"
    path.write_text(
        mapped_content(
            "User 2",
            source_alias="user02",
            first_response='[00:05] **<mark style="background-color: yellow;">A | B</mark>**',
        ),
        encoding="utf-8",
    )
    with pytest.raises(PartialMappingError) as exc:
        merge_mapping_outputs(str(sample_folder))
    assert "MALFORMED_MAPPED_ROW" in exc.value.failures[0]["issues"]


def test_review_manifest_reports_unmapped_and_overlapping_timestamps(sample_folder):
    result = merge_mapping_outputs(str(sample_folder))
    content = open(result["review_manifest"], encoding="utf-8").read()
    assert "Unmapped timestamps" in content
    assert "[00:00]" in content
    assert "[00:05]" in content
