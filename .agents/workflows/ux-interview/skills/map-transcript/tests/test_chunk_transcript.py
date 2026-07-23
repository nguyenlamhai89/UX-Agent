"""Tests for chunk_transcript.py"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "scripts"))

from chunk_transcript import (
    cleanup_chunk_directory,
    estimate_tokens,
    normalize_with_offsets,
    parse_questionnaire_questions,
    normalize_for_search,
    find_question_positions,
    chunk_transcript,
    write_chunks,
)


QUESTIONNAIRE_CONTENT = """# Questionnaire

| # | Theme | Question | Observed Variable |
|---|-------|----------|-------------------|
| 1 | Warm-up | Please introduce yourself | Name |
| 1 | Warm-up | Please introduce yourself | Age |
| 2 | Product | What do you think about product X | First Impression |
| 3 | Product | How often do you use similar products | Usage Frequency |
| 4 | Closing | Any final thoughts | Feedback |
"""

SHORT_TRANSCRIPT = """# Interview Transcript

[00:00] Interviewer: Please introduce yourself.
[00:05] Interviewee: My name is A, I am 25.
[01:00] Interviewer: What do you think about product X?
[01:10] Interviewee: I think it looks great.
[02:00] Interviewer: How often do you use similar products?
[02:10] Interviewee: About once a week.
[03:00] Interviewer: Any final thoughts?
[03:05] Interviewee: No, thanks.
"""

# Generate a long transcript that exceeds token limits
LONG_TRANSCRIPT_TEMPLATE = """# Interview Transcript

[00:00] Interviewer: Please introduce yourself.
[00:05] Interviewee: My name is A, I am 25 years old. {filler1}

[10:00] Interviewer: What do you think about product X?
[10:05] Interviewee: I think it looks great. {filler2}

[20:00] Interviewer: How often do you use similar products?
[20:05] Interviewee: About once a week. {filler3}

[30:00] Interviewer: Any final thoughts?
[30:05] Interviewee: No additional thoughts. {filler4}
"""


class TestEstimateTokens:
    def test_short_text(self):
        assert estimate_tokens("hello world") > 0

    def test_empty_text(self):
        assert estimate_tokens("") == 0

    def test_proportional(self):
        short = estimate_tokens("a" * 100)
        long = estimate_tokens("a" * 1000)
        assert long > short


class TestParseQuestionnaireQuestions:
    def test_extracts_unique_questions(self, tmp_path):
        q_path = tmp_path / "full-questionnaire.md"
        q_path.write_text(QUESTIONNAIRE_CONTENT, encoding="utf-8")

        questions = parse_questionnaire_questions(str(q_path))

        # "Please introduce yourself" appears twice but should be deduplicated
        assert len(questions) == 4
        assert questions[0] == "Please introduce yourself"
        assert questions[1] == "What do you think about product X"
        assert questions[2] == "How often do you use similar products"
        assert questions[3] == "Any final thoughts"

    def test_empty_questionnaire(self, tmp_path):
        q_path = tmp_path / "full-questionnaire.md"
        q_path.write_text("# Empty\n\nNo table here.", encoding="utf-8")

        questions = parse_questionnaire_questions(str(q_path))
        assert questions == []


class TestNormalizeForSearch:
    def test_collapses_whitespace(self):
        assert normalize_for_search("hello   world") == "hello world"

    def test_lowercases(self):
        assert normalize_for_search("Hello World") == "hello world"

    def test_strips(self):
        assert normalize_for_search("  hello  ") == "hello"

    def test_offset_map_points_back_to_original_text(self):
        text = "  Hello\n  world"
        normalized, offsets = normalize_with_offsets(text)
        assert normalized == "hello world"
        world_position = normalized.index("world")
        assert text[offsets[world_position] :].startswith("world")


class TestFindQuestionPositions:
    def test_finds_questions_in_transcript(self):
        questions = [
            "Please introduce yourself",
            "What do you think about product X",
        ]
        positions = find_question_positions(SHORT_TRANSCRIPT, questions)

        assert len(positions) >= 2
        # Positions should be sorted
        for i in range(len(positions) - 1):
            assert positions[i][0] <= positions[i + 1][0]

    def test_no_match_returns_empty(self):
        questions = ["This question does not exist in the transcript at all"]
        positions = find_question_positions(SHORT_TRANSCRIPT, questions)
        assert len(positions) == 0


class TestChunkTranscript:
    def test_no_chunking_for_short_transcript(self):
        questions = ["Please introduce yourself", "What do you think about product X"]
        chunks = chunk_transcript(SHORT_TRANSCRIPT, questions, max_tokens=50000)
        assert chunks == []

    def test_chunks_long_transcript(self, tmp_path):
        """Long transcript should be split into chunks."""
        # Create a transcript that exceeds 100 tokens (using low threshold for test)
        filler = "This is a long response with lots of detail. " * 50
        long_transcript = LONG_TRANSCRIPT_TEMPLATE.format(
            filler1=filler, filler2=filler, filler3=filler, filler4=filler
        )

        questions = [
            "Please introduce yourself",
            "What do you think about product X",
            "How often do you use similar products",
            "Any final thoughts",
        ]

        # Use a very low token threshold to force chunking
        chunks = chunk_transcript(long_transcript, questions, max_tokens=100)

        assert len(chunks) > 1
        # All chunks should have content
        for chunk in chunks:
            assert chunk["content"].strip() != ""
            assert "chunk_index" in chunk
        assert "".join(chunk["content"] for chunk in chunks) == long_transcript

    def test_chunk_indices_are_sequential(self):
        filler = "Word " * 500
        long_transcript = LONG_TRANSCRIPT_TEMPLATE.format(
            filler1=filler, filler2=filler, filler3=filler, filler4=filler
        )
        questions = [
            "Please introduce yourself",
            "What do you think about product X",
            "How often do you use similar products",
            "Any final thoughts",
        ]

        chunks = chunk_transcript(long_transcript, questions, max_tokens=100)

        if chunks:
            for i, chunk in enumerate(chunks):
                assert chunk["chunk_index"] == i

    def test_fallback_without_question_anchors_loses_no_content(self):
        transcript = "".join(
            f"[{index:02d}:00] A long line {index}\n" for index in range(30)
        )
        chunks = chunk_transcript(transcript, ["not present"], max_tokens=20)
        assert len(chunks) > 1
        assert "".join(chunk["content"] for chunk in chunks) == transcript


class TestChunkFiles:
    def test_writes_and_cleans_chunk_directory(self, tmp_path):
        transcript = tmp_path / "transcript_user.md"
        transcript.write_text("source", encoding="utf-8")
        chunks = [
            {
                "content": "first",
                "start_question": "Q1",
                "end_question": "Q1",
                "chunk_index": 0,
            },
            {
                "content": "second",
                "start_question": "Q2",
                "end_question": "Q2",
                "chunk_index": 1,
            },
        ]
        paths = write_chunks(str(tmp_path), str(transcript), chunks)
        assert len(paths) == 2
        assert all(os.path.isfile(path) for path in paths)
        cleanup_chunk_directory(str(tmp_path), str(transcript))
        assert not os.path.exists(tmp_path / ".chunks_transcript_user")
