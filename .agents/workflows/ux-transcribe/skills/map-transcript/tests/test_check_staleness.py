"""Tests for check_staleness.py"""

import os
import time
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "scripts"))

from check_staleness import find_stale_mapped_files


class TestFindStaleFiles:
    def test_detects_stale_mapped_file(self, tmp_path):
        """Mapped file older than transcript should be detected as stale."""
        interview_dir = tmp_path / "Interview"
        interview_dir.mkdir()
        # Create mapped file first (older)
        mapped = interview_dir / "mapped-transcript-Interview_A.md"
        mapped.write_text("# old content", encoding="utf-8")

        # Wait briefly to ensure different mtime
        time.sleep(0.05)

        # Create transcript file second (newer)
        transcript = interview_dir / "transcript_Interview_A.md"
        transcript.write_text("# new transcript", encoding="utf-8")

        stale = find_stale_mapped_files(str(tmp_path))
        assert len(stale) == 1
        assert stale[0]["mapped_file"] == str(mapped)
        assert stale[0]["transcript_file"] == str(transcript)

    def test_no_stale_when_mapped_is_newer(self, tmp_path):
        """Mapped file newer than transcript should not be detected."""
        interview_dir = tmp_path / "Interview"
        interview_dir.mkdir()
        # Create transcript first (older)
        transcript = interview_dir / "transcript_Interview_A.md"
        transcript.write_text("# transcript", encoding="utf-8")

        time.sleep(0.05)

        # Create mapped file second (newer)
        mapped = interview_dir / "mapped-transcript-Interview_A.md"
        mapped.write_text("# mapped content", encoding="utf-8")

        stale = find_stale_mapped_files(str(tmp_path))
        assert len(stale) == 0

    def test_no_stale_when_no_mapped_file(self, tmp_path):
        """No mapped file at all should return empty."""
        interview_dir = tmp_path / "Interview"
        interview_dir.mkdir()
        transcript = interview_dir / "transcript_Interview_A.md"
        transcript.write_text("# transcript", encoding="utf-8")

        stale = find_stale_mapped_files(str(tmp_path))
        assert len(stale) == 0

    def test_multiple_files_mixed_staleness(self, tmp_path):
        """Test with mix of stale and fresh mapped files."""
        interview_dir = tmp_path / "Interview"
        interview_dir.mkdir()
        # Stale pair
        mapped_a = interview_dir / "mapped-transcript-A.md"
        mapped_a.write_text("# old A", encoding="utf-8")
        time.sleep(0.05)
        transcript_a = interview_dir / "transcript_A.md"
        transcript_a.write_text("# new A", encoding="utf-8")

        # Fresh pair
        transcript_b = interview_dir / "transcript_B.md"
        transcript_b.write_text("# old B", encoding="utf-8")
        time.sleep(0.05)
        mapped_b = interview_dir / "mapped-transcript-B.md"
        mapped_b.write_text("# new B", encoding="utf-8")

        stale = find_stale_mapped_files(str(tmp_path))
        assert len(stale) == 1
        assert os.path.basename(stale[0]["mapped_file"]) == "mapped-transcript-A.md"

    def test_ignores_non_matching_files(self, tmp_path):
        """Files that don't match the naming convention should be ignored."""
        interview_dir = tmp_path / "Interview"
        interview_dir.mkdir()
        tmp_path_file = interview_dir / "random_file.md"
        tmp_path_file.write_text("# random", encoding="utf-8")

        stale = find_stale_mapped_files(str(tmp_path))
        assert len(stale) == 0

    def test_questionnaire_change_marks_mapping_stale(self, tmp_path):
        interview_dir = tmp_path / "Interview"
        interview_dir.mkdir()
        transcript = interview_dir / "transcript_A.md"
        transcript.write_text("transcript", encoding="utf-8")
        mapped = interview_dir / "mapped-transcript-A.md"
        mapped.write_text("mapped", encoding="utf-8")
        time.sleep(0.05)
        questionnaire = interview_dir / "full-questionnaire.md"
        questionnaire.write_text("new questionnaire", encoding="utf-8")

        stale = find_stale_mapped_files(str(tmp_path))
        assert len(stale) == 1
        assert stale[0]["mapped_file"] == str(mapped)

    def test_staleness_check_never_deletes_last_valid_file(self, tmp_path):
        interview_dir = tmp_path / "Interview"
        interview_dir.mkdir()
        mapped = interview_dir / "mapped-transcript-A.md"
        mapped.write_text("last valid output", encoding="utf-8")
        time.sleep(0.05)
        transcript = interview_dir / "transcript_A.md"
        transcript.write_text("new transcript", encoding="utf-8")

        assert find_stale_mapped_files(str(tmp_path))
        assert mapped.read_text(encoding="utf-8") == "last valid output"
