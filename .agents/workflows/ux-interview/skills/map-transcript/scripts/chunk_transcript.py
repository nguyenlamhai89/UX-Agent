#!/usr/bin/env python3
"""Split long transcripts at questionnaire anchors without losing content."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import tempfile
from pathlib import Path

from workspace_paths import resolve_workspace_dir


DEFAULT_MAX_TOKENS = 15_000


def estimate_tokens(text: str) -> int:
    """Conservative mixed English/Vietnamese estimate."""
    return len(text) // 3


def parse_questionnaire_questions(questionnaire_path: str) -> list[str]:
    """Extract unique question texts in questionnaire order."""
    questions: list[str] = []
    seen: set[str] = set()
    found_header = False

    with open(questionnaire_path, "r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped.startswith("|"):
                continue
            raw = stripped[1:-1] if stripped.endswith("|") else stripped[1:]
            cells = [cell.strip() for cell in raw.split("|")]
            if not found_header:
                found_header = True
                continue
            if all(
                cell.replace("-", "").replace(":", "").strip() == "" for cell in cells
            ):
                continue
            if len(cells) >= 3:
                question = cells[2]
                if question and question not in seen:
                    seen.add(question)
                    questions.append(question)
    return questions


def normalize_for_search(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().strip())


def normalize_with_offsets(text: str) -> tuple[str, list[int]]:
    """Normalize once and map each normalized character to its original offset."""
    normalized: list[str] = []
    offsets: list[int] = []
    whitespace_pending = False
    whitespace_offset = 0

    for original_index, char in enumerate(text):
        if char.isspace():
            if normalized:
                whitespace_pending = True
                whitespace_offset = original_index
            continue

        if whitespace_pending:
            normalized.append(" ")
            offsets.append(whitespace_offset)
            whitespace_pending = False

        for lowered in char.lower():
            normalized.append(lowered)
            offsets.append(original_index)

    return "".join(normalized), offsets


def find_question_positions(
    transcript_text: str,
    questions: list[str],
) -> list[tuple[int, str]]:
    """Return normalized-text positions for questionnaire question anchors."""
    positions: list[tuple[int, str]] = []
    normalized_transcript, _ = normalize_with_offsets(transcript_text)

    for question in questions:
        normalized_question = normalize_for_search(question)
        position = normalized_transcript.find(normalized_question)
        if position >= 0:
            positions.append((position, question))
            continue

        words = normalized_question.split()
        if len(words) >= 4:
            for end in range(len(words), max(3, len(words) // 2), -1):
                position = normalized_transcript.find(" ".join(words[:end]))
                if position >= 0:
                    positions.append((position, question))
                    break

    positions.sort(key=lambda item: item[0])
    return positions


def _split_at_line_boundaries(text: str, max_chars: int) -> list[str]:
    """Split oversized text without cutting a transcript line or losing bytes."""
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    current: list[str] = []
    current_size = 0
    for line in text.splitlines(keepends=True):
        if current and current_size + len(line) > max_chars:
            pieces.append("".join(current))
            current = []
            current_size = 0
        if len(line) > max_chars:
            if current:
                pieces.append("".join(current))
                current = []
                current_size = 0
            for start in range(0, len(line), max_chars):
                pieces.append(line[start : start + max_chars])
            continue
        current.append(line)
        current_size += len(line)
    if current:
        pieces.append("".join(current))
    return pieces


def chunk_transcript(
    transcript_text: str,
    questions: list[str],
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[dict]:
    """Return deterministic chunks whose concatenated content equals the input."""
    if max_tokens <= 0:
        raise ValueError("max_tokens must be greater than zero")
    if estimate_tokens(transcript_text) <= max_tokens:
        return []

    normalized_transcript, offsets = normalize_with_offsets(transcript_text)
    normalized_positions = find_question_positions(transcript_text, questions)
    max_chars = max_tokens * 3

    anchors: list[tuple[int, str]] = []
    for normalized_position, question in normalized_positions:
        if normalized_position < len(offsets):
            anchors.append((offsets[normalized_position], question))
    anchors.sort(key=lambda item: item[0])

    sections: list[tuple[str, str, str]] = []
    if not anchors:
        for piece in _split_at_line_boundaries(transcript_text, max_chars):
            sections.append((piece, "(positional)", "(positional)"))
    else:
        for index, (position, question) in enumerate(anchors):
            start = 0 if index == 0 else position
            end = (
                anchors[index + 1][0]
                if index + 1 < len(anchors)
                else len(transcript_text)
            )
            end_question = (
                anchors[index + 1][1] if index + 1 < len(anchors) else question
            )
            section = transcript_text[start:end]
            for piece in _split_at_line_boundaries(section, max_chars):
                sections.append((piece, question, end_question))

    chunks: list[dict] = []
    current_content: list[str] = []
    current_size = 0
    current_start = sections[0][1] if sections else "(start)"
    current_end = current_start

    for content, start_question, end_question in sections:
        if current_content and current_size + len(content) > max_chars:
            chunks.append(
                {
                    "content": "".join(current_content),
                    "start_question": current_start,
                    "end_question": current_end,
                    "chunk_index": len(chunks),
                }
            )
            current_content = []
            current_size = 0
            current_start = start_question
        elif not current_content:
            current_start = start_question
        current_content.append(content)
        current_size += len(content)
        current_end = end_question

    if current_content:
        chunks.append(
            {
                "content": "".join(current_content),
                "start_question": current_start,
                "end_question": current_end,
                "chunk_index": len(chunks),
            }
        )

    return chunks


def chunk_directory(interview_dir: str, transcript_file: str) -> str:
    basename = Path(transcript_file).stem
    return os.path.join(interview_dir, f".chunks_{basename}")


def cleanup_chunk_directory(interview_dir: str, transcript_file: str) -> None:
    directory = chunk_directory(interview_dir, transcript_file)
    if os.path.isdir(directory):
        shutil.rmtree(directory)


def write_chunks(
    interview_dir: str,
    transcript_file: str,
    chunks: list[dict],
) -> list[str]:
    """Atomically write chunk files after clearing an older chunk set."""
    cleanup_chunk_directory(interview_dir, transcript_file)
    if not chunks:
        return []

    directory = chunk_directory(interview_dir, transcript_file)
    os.makedirs(directory, exist_ok=True)
    paths: list[str] = []

    try:
        for chunk in chunks:
            filename = f"chunk_{chunk['chunk_index']:02d}.md"
            destination = os.path.join(directory, filename)
            header = (
                f"# Transcript Chunk {chunk['chunk_index'] + 1}/{len(chunks)}\n"
                f"> Questions covered: {chunk['start_question']} → {chunk['end_question']}\n\n"
            )
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{filename}.", suffix=".tmp", dir=directory
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(header)
                    handle.write(chunk["content"])
                os.replace(temporary, destination)
            except Exception:
                if os.path.exists(temporary):
                    os.remove(temporary)
                raise
            paths.append(destination)
    except Exception:
        cleanup_chunk_directory(interview_dir, transcript_file)
        raise
    return paths


def chunk_transcript_file(
    folder_path: str,
    transcript_file: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[str]:
    workspace_dir = resolve_workspace_dir(folder_path)
    questionnaire_path = os.path.join(workspace_dir, "full-questionnaire.md")
    questions = parse_questionnaire_questions(questionnaire_path)
    with open(transcript_file, "r", encoding="utf-8") as handle:
        transcript_text = handle.read()
    chunks = chunk_transcript(transcript_text, questions, max_tokens)
    return write_chunks(workspace_dir, transcript_file, chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder_path")
    parser.add_argument("transcript_file")
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    args = parser.parse_args()

    workspace_dir = resolve_workspace_dir(args.folder_path)
    questionnaire_path = os.path.join(workspace_dir, "full-questionnaire.md")
    if not os.path.isdir(args.folder_path):
        print(f"Error: '{args.folder_path}' is not a valid directory.")
        raise SystemExit(1)
    if not os.path.isdir(workspace_dir):
        print(f"Error: '{workspace_dir}' does not exist.")
        raise SystemExit(1)
    if not os.path.isfile(questionnaire_path):
        print("Error: full-questionnaire.md not found.")
        raise SystemExit(1)
    if not os.path.isfile(args.transcript_file):
        print(f"Error: '{args.transcript_file}' not found.")
        raise SystemExit(1)

    paths = chunk_transcript_file(
        args.folder_path,
        args.transcript_file,
        args.max_tokens,
    )
    if not paths:
        print("NO_CHUNKING_NEEDED")
        return
    print(f"CHUNKS_CREATED:{len(paths)}")
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
