#!/usr/bin/env python3
"""
check_staleness.py

Checks for stale mapped-transcript files by comparing modification timestamps
of transcript source files against their corresponding mapped output files.
Deletes stale mapped files so they will be regenerated.

Usage:
    python3 check_staleness.py <folder_path>
"""

import os
import sys
import re
import glob


def find_stale_mapped_files(folder_path):
    """
    Compare transcript_<audio_name>.md timestamps against
    mapped-transcript-<audio_name>.md timestamps.

    Returns:
        list[dict]: List of stale files with keys:
            - transcript_file: source transcript path
            - mapped_file: stale mapped file path
            - transcript_mtime: source modification time
            - mapped_mtime: mapped file modification time
    """
    stale_files = []

    interview_dir = os.path.join(folder_path, "Interview")
    if not os.path.exists(interview_dir):
        return stale_files
        
    # Find all transcript files
    transcript_pattern = os.path.join(interview_dir, "transcript_*.md")
    transcript_files = glob.glob(transcript_pattern)

    for transcript_path in transcript_files:
        basename = os.path.basename(transcript_path)
        # Extract audio_name from transcript_<audio_name>.md
        match = re.match(r"transcript_(.+)\.md$", basename)
        if not match:
            continue

        audio_name = match.group(1)
        mapped_path = os.path.join(
            interview_dir, f"mapped-transcript-{audio_name}.md"
        )

        if not os.path.exists(mapped_path):
            continue

        transcript_mtime = os.path.getmtime(transcript_path)
        mapped_mtime = os.path.getmtime(mapped_path)

        if transcript_mtime > mapped_mtime:
            stale_files.append({
                "transcript_file": transcript_path,
                "mapped_file": mapped_path,
                "transcript_mtime": transcript_mtime,
                "mapped_mtime": mapped_mtime,
            })

    return stale_files


def delete_stale_files(stale_files):
    """
    Delete stale mapped transcript files.

    Args:
        stale_files: List of stale file dicts from find_stale_mapped_files.

    Returns:
        list[str]: List of deleted file paths.
    """
    deleted = []
    for entry in stale_files:
        mapped_path = entry["mapped_file"]
        try:
            os.remove(mapped_path)
            deleted.append(mapped_path)
        except OSError as e:
            print(
                f"WARNING: Could not delete stale file {mapped_path}: {e}",
                file=sys.stderr,
            )
    return deleted


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 check_staleness.py <folder_path>")
        sys.exit(1)

    folder_path = sys.argv[1]

    if not os.path.isdir(folder_path):
        print(f"Error: '{folder_path}' is not a valid directory.")
        sys.exit(1)

    stale = find_stale_mapped_files(folder_path)

    if not stale:
        print("No stale mapped transcript files found.")
        sys.exit(0)

    print(f"Found {len(stale)} stale mapped transcript file(s):")
    for entry in stale:
        print(f"  - {os.path.basename(entry['mapped_file'])} "
              f"(transcript is newer)")

    deleted = delete_stale_files(stale)
    print(f"Deleted {len(deleted)} stale file(s). They will be regenerated.")
