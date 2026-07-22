import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts")))

from insight_schema import (
    SchemaError,
    build_evidence_index,
    derive_insights_data,
    parse_mapped_transcript,
    render_participant_view,
    validate_extraction_candidate,
    validate_master_candidate,
)
from saturation_test_helpers import create_canonical, extraction_candidate


def test_parser_accepts_only_canonical_combined_filename(tmp_path):
    mapped_file = create_canonical(tmp_path)
    parsed = parse_mapped_transcript(str(mapped_file))
    assert parsed.interviewees == ["user01", "user02"]
    assert parsed.rows[1]["responses"]["user01"].startswith("[00:15]")

    renamed = mapped_file.with_name("mapped-transcript-user01.md")
    renamed.write_text(mapped_file.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(SchemaError, match="basename"):
        parse_mapped_transcript(str(renamed.resolve()))


def test_parser_rejects_partial_and_relative_paths(tmp_path, monkeypatch):
    mapped_file = create_canonical(tmp_path)
    partial = mapped_file.with_name("mapped-transcript.partial.md")
    partial.write_text(mapped_file.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(SchemaError, match="basename"):
        parse_mapped_transcript(str(partial.resolve()))
    monkeypatch.chdir(mapped_file.parent)
    with pytest.raises(SchemaError, match="absolute"):
        parse_mapped_transcript("mapped-transcript.md")


def test_parser_rejects_malformed_width_and_missing_timestamp(tmp_path):
    mapped_file = create_canonical(tmp_path)
    content = mapped_file.read_text(encoding="utf-8").replace(
        "The workflow works for user02</mark>** |",
        "The workflow works for user02</mark>** | extra |",
    )
    mapped_file.write_text(content, encoding="utf-8")
    with pytest.raises(SchemaError, match="cells"):
        parse_mapped_transcript(str(mapped_file))

    mapped_file = create_canonical(tmp_path)
    mapped_file.write_text(
        mapped_file.read_text(encoding="utf-8").replace("[00:15]", "", 1),
        encoding="utf-8",
    )
    with pytest.raises(SchemaError, match="lacks a timestamp"):
        parse_mapped_transcript(str(mapped_file))


def test_participant_view_is_derived_from_combined_file(tmp_path):
    mapped = parse_mapped_transcript(str(create_canonical(tmp_path)))
    view = render_participant_view(mapped, "user01")
    assert "user01" in view
    assert "user02" not in view
    assert "The workflow works for user01" in view


def test_extraction_candidate_requires_exact_grounding(tmp_path):
    mapped = parse_mapped_transcript(str(create_canonical(tmp_path)))
    candidate = extraction_candidate("user01")
    validated = validate_extraction_candidate(candidate, mapped, "user01")
    assert validated["insights"][0]["evidence"][0]["evidence_id"].startswith("ev-")

    candidate["insights"][0]["evidence"][0]["quote"] = "Fabricated quote"
    with pytest.raises(SchemaError, match="not grounded"):
        validate_extraction_candidate(candidate, mapped, "user01")


def test_extraction_cannot_cite_another_participant_or_row(tmp_path):
    mapped = parse_mapped_transcript(str(create_canonical(tmp_path)))
    candidate = extraction_candidate("user01")
    candidate["insights"][0]["evidence"][0]["quote"] = "The workflow works for user02"
    with pytest.raises(SchemaError, match="not grounded"):
        validate_extraction_candidate(candidate, mapped, "user01")

    candidate = extraction_candidate("user01")
    candidate["insights"][0]["evidence"][0]["observed_variable"] = "Identity"
    with pytest.raises(SchemaError, match="does not match"):
        validate_extraction_candidate(candidate, mapped, "user01")


def test_master_candidate_requires_exact_evidence_coverage(tmp_path):
    mapped = parse_mapped_transcript(str(create_canonical(tmp_path)))
    extraction = validate_extraction_candidate(
        extraction_candidate("user01"), mapped, "user01"
    )
    evidence = build_evidence_index([extraction])
    candidate = {
        "master_insights": [
            {
                "theme": "Product value",
                "insight": "Satisfied with the workflow, because it works reliably",
                "evidence_ids": list(evidence),
            }
        ]
    }
    validated = validate_master_candidate(candidate, evidence, set(evidence))
    assert validated == candidate
    candidate["master_insights"][0]["evidence_ids"] = []
    with pytest.raises(SchemaError, match="non-empty"):
        validate_master_candidate(candidate, evidence, set(evidence))


def test_statuses_follow_interviewee_column_order(tmp_path):
    mapped = parse_mapped_transcript(str(create_canonical(tmp_path)))
    extractions = [
        validate_extraction_candidate(extraction_candidate(name), mapped, name)
        for name in mapped.interviewees
    ]
    evidence = build_evidence_index(extractions)
    master = {
        "master_insights": [
            {
                "theme": "Product value",
                "insight": "Satisfied with the workflow, because it works reliably",
                "evidence_ids": list(evidence),
            }
        ]
    }
    data = derive_insights_data(
        mapped,
        master,
        evidence,
        {"sha256": "abc", "size": 1, "mtime_ns": 1},
    )
    entries = data["master_insights"][0]["interviewees"]
    assert entries["user01"]["status"] == "new"
    assert entries["user02"]["status"] == "repeated"
