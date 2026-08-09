"""Resolve the directory shared by transcription and transcript mapping."""

from __future__ import annotations

import glob
import os


QUESTIONNAIRE_FILENAME = "full-questionnaire.md"
TRANSCRIPT_PATTERN = "transcript_*.md"
MANIFEST_FILENAME = "mapping-manifest.json"


def candidate_workspace_dirs(folder_path: str) -> list[str]:
    """Return the canonical Interview directory followed by the direct folder."""
    root = os.path.abspath(folder_path)
    interview_dir = os.path.join(root, "Interview")
    candidates = [interview_dir, root] if interview_dir != root else [root]
    return [path for path in candidates if os.path.isdir(path)]


def has_mapping_inputs(directory: str) -> bool:
    """Return whether a directory contains the complete mapping source pair."""
    return bool(
        os.path.isfile(os.path.join(directory, QUESTIONNAIRE_FILENAME))
        and glob.glob(os.path.join(directory, TRANSCRIPT_PATTERN))
    )


def resolve_workspace_dir(folder_path: str) -> str:
    """Prefer a complete Interview handoff, otherwise support direct-folder input."""
    candidates = candidate_workspace_dirs(folder_path)
    for directory in candidates:
        if has_mapping_inputs(directory):
            return directory
    for directory in candidates:
        if os.path.isfile(os.path.join(directory, QUESTIONNAIRE_FILENAME)) or glob.glob(
            os.path.join(directory, TRANSCRIPT_PATTERN)
        ):
            return directory
    return candidates[0] if candidates else os.path.abspath(folder_path)


def manifest_path(folder_path: str, workspace_dir: str | None = None) -> str:
    """Return the manifest path for a resolved workspace directory."""
    return os.path.join(
        workspace_dir or resolve_workspace_dir(folder_path), MANIFEST_FILENAME
    )


def existing_manifest_path(folder_path: str) -> str:
    """Prefer the active workspace manifest, then support a legacy location."""
    active_workspace = resolve_workspace_dir(folder_path)
    candidates = [active_workspace, *candidate_workspace_dirs(folder_path)]
    for directory in dict.fromkeys(candidates):
        path = manifest_path(folder_path, directory)
        if os.path.isfile(path):
            return path
    return manifest_path(folder_path, active_workspace)
