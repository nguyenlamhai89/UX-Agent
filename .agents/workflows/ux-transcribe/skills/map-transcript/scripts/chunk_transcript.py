#!/usr/bin/env python3
"""
chunk_transcript.py

Deterministically splits transcript files into logical chunks using the
questionnaire structure as anchors. This ensures no mapping data is lost
at chunk boundaries.

The script searches for question text from the questionnaire within the
transcript and splits at those boundaries, producing numbered chunk files.

Usage:
    python3 chunk_transcript.py <folder_path> <transcript_file> [--max-tokens 15000]

Output:
    If chunking is needed: writes chunk files and prints their paths (one per line).
    If no chunking needed: prints "NO_CHUNKING_NEEDED" and exits.
"""

import os
import sys
import re
import argparse


def estimate_tokens(text):
    """Rough token estimate: ~4 chars per token for English, ~2 for Vietnamese."""
    return len(text) // 3  # conservative estimate for mixed content


def parse_questionnaire_questions(questionnaire_path):
    """
    Extract ordered list of question texts from full-questionnaire.md.

    Returns:
        list[str]: Unique question texts in order, deduplicated
                   (since multiple observed variables share the same question).
    """
    with open(questionnaire_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    questions = []
    seen = set()
    found_header = False

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue

        cells = [cell.strip() for cell in stripped.split("|")]
        cells = cells[1:-1] if len(cells) > 2 else cells

        if not found_header:
            found_header = True
            continue

        # Skip separator row
        if all(c.replace("-", "").replace(":", "").strip() == "" for c in cells):
            continue

        # Question is in column index 2 (0=#, 1=Theme, 2=Question)
        if len(cells) >= 3:
            question = cells[2].strip()
            if question and question not in seen:
                questions.append(question)
                seen.add(question)

    return questions


def normalize_for_search(text):
    """Normalize text for fuzzy matching: lowercase, collapse whitespace."""
    return re.sub(r"\s+", " ", text.lower().strip())


def find_question_positions(transcript_text, questions):
    """
    Find the character positions where each questionnaire question appears
    in the transcript.

    Uses fuzzy matching: normalizes whitespace and case, and searches for
    substantial substrings of the question text.

    Returns:
        list[tuple[int, str]]: Sorted list of (position, question_text) pairs.
    """
    positions = []
    normalized_transcript = normalize_for_search(transcript_text)

    for question in questions:
        normalized_q = normalize_for_search(question)

        # Try exact normalized match first
        pos = normalized_transcript.find(normalized_q)
        if pos >= 0:
            positions.append((pos, question))
            continue

        # Try matching significant words (at least 4 words) from the question
        words = normalized_q.split()
        if len(words) >= 4:
            # Try progressively shorter substrings from the start
            for end in range(len(words), max(3, len(words) // 2), -1):
                substr = " ".join(words[:end])
                pos = normalized_transcript.find(substr)
                if pos >= 0:
                    positions.append((pos, question))
                    break

    # Sort by position in transcript
    positions.sort(key=lambda x: x[0])
    return positions


def chunk_transcript(transcript_text, questions, max_tokens=15000):
    """
    Split transcript into chunks at question boundaries.

    Each chunk contains the transcript content from one question boundary
    to the next, ensuring no data is split mid-conversation.

    Args:
        transcript_text: Full transcript content.
        questions: List of question texts from questionnaire.
        max_tokens: Maximum tokens per chunk.

    Returns:
        list[dict]: List of chunks with keys:
            - content: chunk text content
            - start_question: first question in this chunk
            - end_question: last question in this chunk
            - chunk_index: 0-based index
        Returns empty list if no chunking is needed.
    """
    total_tokens = estimate_tokens(transcript_text)
    if total_tokens <= max_tokens:
        return []

    # Find question positions in transcript
    positions = find_question_positions(transcript_text, questions)

    if not positions:
        # Fallback: can't find questions, split by approximate token boundaries
        chunk_size = max_tokens * 3  # chars per chunk (rough)
        chunks = []
        for i in range(0, len(transcript_text), chunk_size):
            chunk_text = transcript_text[i:i + chunk_size]
            chunks.append({
                "content": chunk_text,
                "start_question": f"(positional chunk {len(chunks) + 1})",
                "end_question": f"(positional chunk {len(chunks) + 1})",
                "chunk_index": len(chunks),
            })
        return chunks

    # Build chunks at question boundaries
    chunks = []
    current_start = 0
    current_start_question = positions[0][1] if positions else "(start)"
    current_chunk_questions = []

    # Map character positions back to original text positions
    # (our positions are in normalized space, need original positions)
    lines = transcript_text.split("\n")
    line_positions = []
    pos = 0
    for line in lines:
        line_positions.append(pos)
        pos += len(line) + 1

    for i, (norm_pos, question) in enumerate(positions):
        # Find the actual line in original text containing this question
        actual_pos = 0
        normalized_so_far = ""
        for j, line in enumerate(lines):
            normalized_so_far = normalize_for_search(
                "\n".join(lines[: j + 1])
            )
            if len(normalized_so_far) >= norm_pos:
                actual_pos = line_positions[j]
                break

        current_chunk_questions.append(question)
        chunk_text = transcript_text[current_start:actual_pos]
        chunk_tokens = estimate_tokens(chunk_text)

        # Check if adding the next section would exceed max tokens
        if chunk_tokens >= max_tokens and len(current_chunk_questions) > 1:
            # Close current chunk (exclude current question, it goes to next)
            chunks.append({
                "content": transcript_text[current_start:actual_pos],
                "start_question": current_start_question,
                "end_question": current_chunk_questions[-2],
                "chunk_index": len(chunks),
            })
            current_start = actual_pos
            current_start_question = question
            current_chunk_questions = [question]

    # Add final chunk (remaining content)
    remaining = transcript_text[current_start:]
    if remaining.strip():
        chunks.append({
            "content": remaining,
            "start_question": current_start_question,
            "end_question": positions[-1][1] if positions else "(end)",
            "chunk_index": len(chunks),
        })

    return chunks


def main():
    parser = argparse.ArgumentParser(
        description="Deterministically chunk transcripts using questionnaire anchors."
    )
    parser.add_argument("folder_path", help="Path to folder with questionnaire.")
    parser.add_argument("transcript_file", help="Path to the transcript file to chunk.")
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=15000,
        help="Maximum tokens per chunk (default: 15000).",
    )
    args = parser.parse_args()

    if not os.path.isdir(args.folder_path):
        print(f"Error: '{args.folder_path}' is not a valid directory.")
        sys.exit(1)

    interview_dir = os.path.join(args.folder_path, "Interview")
    if not os.path.exists(interview_dir):
        print(f"Error: '{interview_dir}' does not exist.")
        sys.exit(1)

    questionnaire_path = os.path.join(interview_dir, "full-questionnaire.md")
    if not os.path.exists(questionnaire_path):
        print("Error: full-questionnaire.md not found.")
        sys.exit(1)

    if not os.path.exists(args.transcript_file):
        print(f"Error: '{args.transcript_file}' not found.")
        sys.exit(1)

    # Parse questionnaire questions
    questions = parse_questionnaire_questions(questionnaire_path)

    # Read transcript
    with open(args.transcript_file, "r", encoding="utf-8") as f:
        transcript_text = f.read()

    # Chunk the transcript
    chunks = chunk_transcript(transcript_text, questions, args.max_tokens)

    if not chunks:
        print("NO_CHUNKING_NEEDED")
        sys.exit(0)

    # Write chunk files
    transcript_basename = os.path.splitext(os.path.basename(args.transcript_file))[0]
    chunk_dir = os.path.join(interview_dir, f".chunks_{transcript_basename}")
    os.makedirs(chunk_dir, exist_ok=True)

    print(f"CHUNKS_CREATED:{len(chunks)}")
    for chunk in chunks:
        chunk_filename = f"chunk_{chunk['chunk_index']:02d}.md"
        chunk_path = os.path.join(chunk_dir, chunk_filename)

        header = (
            f"# Transcript Chunk {chunk['chunk_index'] + 1}/{len(chunks)}\n"
            f"> Questions covered: {chunk['start_question']} → {chunk['end_question']}\n\n"
        )

        with open(chunk_path, "w", encoding="utf-8") as f:
            f.write(header + chunk["content"])

        print(chunk_path)


if __name__ == "__main__":
    main()
