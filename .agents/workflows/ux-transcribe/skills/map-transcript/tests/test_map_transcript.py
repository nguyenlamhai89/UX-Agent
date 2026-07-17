import os
import pytest
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "scripts"))

from map_transcript import (
    parse_markdown_table,
    find_questionnaire,
    find_mapped_transcripts,
    extract_audio_name,
    merge_mapped_transcripts,
)


QUESTIONNAIRE_CONTENT = """# Questionnaire

| # | Theme | Question | Observed Variable |
|---|-------|----------|-------------------|
| 1 | Warm-up | Please introduce yourself | Name |
| 1 | Warm-up | Please introduce yourself | Age |
| 2 | Warm-up | How was your day today | Journey |
| 3 | Product | What do you think about X | First Impression |
"""

MAPPED_TRANSCRIPT_A = """# Mapped Transcript

| # | Theme | Question | Observed Variable | Interviewee_A |
|---|-------|----------|-------------------|---------------|
| 1 | Warm-up | Please introduce yourself | Name | My name is A |
| 1 | Warm-up | Please introduce yourself | Age | 25 years old |
| 2 | Warm-up | How was your day today | Journey | It was good |
| 3 | Product | What do you think about X | First Impression | N/A |
"""

MAPPED_TRANSCRIPT_B = """# Mapped Transcript

| # | Theme | Question | Observed Variable | Interviewee_B |
|---|-------|----------|-------------------|---------------|
| 1 | Warm-up | Please introduce yourself | Name | I am B |
| 1 | Warm-up | Please introduce yourself | Age | 30 years old |
| 2 | Warm-up | How was your day today | Journey | N/A |
| 3 | Product | What do you think about X | First Impression | It looks great |
"""

MAPPED_TRANSCRIPT_C_HTML = """# Mapped Transcript

| # | Theme | Question | Observed Variable | Interviewee_C |
|---|-------|----------|-------------------|---------------|
| 1 | Warm-up | Please introduce yourself | Name | I am C<br>I work at XYZ |
| 1 | Warm-up | Please introduce yourself | Age | 28 years old |
| 2 | Warm-up | How was your day today | Journey | Good.<br><br>Very good. |
| 3 | Product | What do you think about X | First Impression | **<mark style="background-color: yellow;">Loved it!</mark>** |
"""


@pytest.fixture
def sample_folder(tmp_path):
    """Create a sample folder with questionnaire and mapped transcript files."""
    interview_dir = tmp_path / "Interview"
    interview_dir.mkdir()
    
    # Write questionnaire
    q_path = interview_dir / "full-questionnaire.md"
    q_path.write_text(QUESTIONNAIRE_CONTENT, encoding="utf-8")

    # Write mapped transcripts
    mt_a = interview_dir / "mapped-transcript-Interviewee_A.md"
    mt_a.write_text(MAPPED_TRANSCRIPT_A, encoding="utf-8")

    mt_b = interview_dir / "mapped-transcript-Interviewee_B.md"
    mt_b.write_text(MAPPED_TRANSCRIPT_B, encoding="utf-8")

    return tmp_path


class TestParseMarkdownTable:
    def test_parses_headers_and_rows(self, tmp_path):
        filepath = tmp_path / "test.md"
        filepath.write_text(QUESTIONNAIRE_CONTENT, encoding="utf-8")

        headers, rows = parse_markdown_table(str(filepath))

        assert headers == ["#", "Theme", "Question", "Observed Variable"]
        assert len(rows) == 4
        assert rows[0] == ["1", "Warm-up", "Please introduce yourself", "Name"]
        assert rows[3] == ["3", "Product", "What do you think about X", "First Impression"]

    def test_parses_mapped_transcript_with_interviewee_column(self, tmp_path):
        filepath = tmp_path / "mapped.md"
        filepath.write_text(MAPPED_TRANSCRIPT_A, encoding="utf-8")

        headers, rows = parse_markdown_table(str(filepath))

        assert headers == ["#", "Theme", "Question", "Observed Variable", "Interviewee_A"]
        assert len(rows) == 4
        assert rows[0][-1] == "My name is A"
        assert rows[3][-1] == "N/A"

    def test_empty_file_returns_empty(self, tmp_path):
        filepath = tmp_path / "empty.md"
        filepath.write_text("# No table here\n\nJust some text.\n", encoding="utf-8")

        headers, rows = parse_markdown_table(str(filepath))

        assert headers == []
        assert rows == []


class TestFindQuestionnaire:
    def test_finds_questionnaire(self, sample_folder):
        result = find_questionnaire(str(sample_folder / "Interview"))
        assert result is not None
        assert result.endswith("full-questionnaire.md")

    def test_returns_none_when_missing(self, tmp_path):
        result = find_questionnaire(str(tmp_path))
        assert result is None


class TestFindMappedTranscripts:
    def test_finds_mapped_transcripts(self, sample_folder):
        results = find_mapped_transcripts(str(sample_folder / "Interview"))
        assert len(results) == 2
        basenames = [os.path.basename(f) for f in results]
        assert "mapped-transcript-Interviewee_A.md" in basenames
        assert "mapped-transcript-Interviewee_B.md" in basenames

    def test_excludes_combined_file(self, sample_folder):
        # Create the combined file
        combined = sample_folder / "Interview" / "mapped-transcript.md"
        combined.write_text("# Combined\n", encoding="utf-8")

        results = find_mapped_transcripts(str(sample_folder / "Interview"))
        basenames = [os.path.basename(f) for f in results]
        assert "mapped-transcript.md" not in basenames
        assert len(results) == 2

    def test_returns_empty_when_no_files(self, tmp_path):
        results = find_mapped_transcripts(str(tmp_path))
        assert results == []


class TestExtractAudioName:
    def test_extracts_name(self):
        assert extract_audio_name("mapped-transcript-HR_Leanbase.md") == "HR_Leanbase"
        assert extract_audio_name("mapped-transcript-Nguyen_Thi_Dung.md") == "Nguyen_Thi_Dung"

    def test_returns_none_for_invalid(self):
        assert extract_audio_name("full-questionnaire.md") is None
        assert extract_audio_name("mapped-transcript.md") is None
        assert extract_audio_name("random-file.md") is None


class TestMergeMappedTranscripts:
    def test_merge_produces_correct_output(self, sample_folder):
        output_path = merge_mapped_transcripts(str(sample_folder))

        assert os.path.exists(output_path)
        assert output_path.endswith("mapped-transcript.md")

        headers, rows = parse_markdown_table(output_path)

        # Should have base 4 columns + 2 interviewee columns
        assert len(headers) == 6
        assert headers[:4] == ["#", "Theme", "Question", "Observed Variable"]
        assert "Interviewee_A" in headers
        assert "Interviewee_B" in headers

        # Should have 4 data rows
        assert len(rows) == 4

    def test_merge_preserves_response_content(self, sample_folder):
        output_path = merge_mapped_transcripts(str(sample_folder))
        headers, rows = parse_markdown_table(output_path)

        idx_a = headers.index("Interviewee_A")
        idx_b = headers.index("Interviewee_B")

        # First row: Name
        assert rows[0][idx_a] == "My name is A"
        assert rows[0][idx_b] == "I am B"

        # Last row: First Impression
        assert rows[3][idx_a] == "N/A"
        assert rows[3][idx_b] == "It looks great"

    def test_merge_raises_when_no_questionnaire(self, tmp_path):
        interview_dir = tmp_path / "Interview"
        interview_dir.mkdir()
        # Create a mapped transcript but no questionnaire
        mt = interview_dir / "mapped-transcript-Test.md"
        mt.write_text(MAPPED_TRANSCRIPT_A, encoding="utf-8")

        with pytest.raises(FileNotFoundError, match="full-questionnaire.md"):
            merge_mapped_transcripts(str(tmp_path))

    def test_merge_raises_when_no_mapped_files(self, tmp_path):
        interview_dir = tmp_path / "Interview"
        interview_dir.mkdir()
        # Create questionnaire but no mapped transcripts
        q = interview_dir / "full-questionnaire.md"
        q.write_text(QUESTIONNAIRE_CONTENT, encoding="utf-8")

        with pytest.raises(ValueError, match="No mapped-transcript"):
            merge_mapped_transcripts(str(tmp_path))

    def test_merge_output_format(self, sample_folder):
        output_path = merge_mapped_transcripts(str(sample_folder))

        with open(output_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Should start with heading
        assert content.startswith("# Mapped Transcript")

        # Should contain table separator
        assert "| --- |" in content

        # Should not be wrapped in code fences
        assert "```" not in content

    def test_merge_with_html_br_tags(self, tmp_path):
        interview_dir = tmp_path / "Interview"
        interview_dir.mkdir()
        # Write questionnaire
        q_path = interview_dir / "full-questionnaire.md"
        q_path.write_text(QUESTIONNAIRE_CONTENT, encoding="utf-8")

        # Write mapped transcript with HTML tags
        mt_c = interview_dir / "mapped-transcript-Interviewee_C.md"
        mt_c.write_text(MAPPED_TRANSCRIPT_C_HTML, encoding="utf-8")

        output_path = merge_mapped_transcripts(str(tmp_path))
        headers, rows = parse_markdown_table(output_path)

        assert "Interviewee_C" in headers
        idx_c = headers.index("Interviewee_C")

        # Ensure HTML tags are preserved and row parsing didn't break
        assert rows[0][idx_c] == "I am C<br>I work at XYZ"
        assert rows[2][idx_c] == "Good.<br><br>Very good."
        assert rows[3][idx_c] == "**<mark style=\"background-color: yellow;\">Loved it!</mark>**"
