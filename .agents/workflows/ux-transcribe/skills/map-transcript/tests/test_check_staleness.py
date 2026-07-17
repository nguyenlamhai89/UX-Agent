"""Tests for check_staleness.py"""

import os
import time
import pytest
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "scripts"))

from check_staleness import find_stale_mapped_files, delete_stale_files


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


class TestDeleteStaleFiles:
    def test_deletes_stale_files(self, tmp_path):
        """Stale mapped files should be deleted."""
        mapped = tmp_path / "mapped-transcript-A.md"
        mapped.write_text("# stale content", encoding="utf-8")

        stale = [{
            "transcript_file": str(tmp_path / "transcript_A.md"),
            "mapped_file": str(mapped),
            "transcript_mtime": time.time(),
            "mapped_mtime": time.time() - 100,
        }]

        deleted = delete_stale_files(stale)
        assert len(deleted) == 1
        assert not os.path.exists(str(mapped))

    def test_handles_already_deleted(self, tmp_path):
        """Should handle gracefully if file was already deleted."""
        stale = [{
            "transcript_file": str(tmp_path / "transcript_A.md"),
            "mapped_file": str(tmp_path / "mapped-transcript-nonexistent.md"),
            "transcript_mtime": time.time(),
            "mapped_mtime": time.time() - 100,
        }]

        deleted = delete_stale_files(stale)
        assert len(deleted) == 0
