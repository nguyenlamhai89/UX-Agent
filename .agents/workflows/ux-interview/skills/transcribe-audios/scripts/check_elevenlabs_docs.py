#!/usr/bin/env python3
"""Verify the live official ElevenLabs Speech to Text documentation contract.

This is intentionally a preflight check, not a second API implementation. The
skill follows the official pages below for request parameters, response shape,
limits, batch/realtime boundaries, and feature behavior. A strict check fails
closed when the documentation cannot be reached or the expected API contract
markers are missing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone


DOCS = (
    {
        "name": "Speech to Text overview",
        "url": "https://elevenlabs.io/docs/overview/capabilities/speech-to-text",
        "markers": ("Scribe v2", "keyterm prompting", "speaker diarization"),
    },
    {
        "name": "Speech to Text quickstart",
        "url": "https://elevenlabs.io/docs/eleven-api/guides/cookbooks/speech-to-text",
        "markers": ("speech_to_text.convert", "model_id", "diarize"),
    },
    {
        "name": "Create transcript API reference",
        "url": "https://elevenlabs.io/docs/api-reference/speech-to-text/convert",
        "markers": (
            "tag_audio_events",
            "language_code",
            "timestamps_granularity",
            "diarize",
            "num_speakers",
            "no_verbatim",
        ),
    },
    {
        "name": "Keyterm prompting",
        "url": "https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/batch/keyterm-prompting",
        "markers": ("keyterms", "1000", "50 characters"),
    },
    {
        "name": "Multichannel transcription",
        "url": "https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/batch/multichannel-transcription",
        "markers": ("use_multi_channel", "multichannel_output_style", "channel_index"),
    },
    {
        "name": "Asynchronous Speech to Text",
        "url": "https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/batch/webhooks",
        "markers": ("webhook", "transcription completed", "signature"),
    },
    {
        "name": "Realtime Speech to Text event reference",
        "url": "https://elevenlabs.io/docs/eleven-api/guides/how-to/speech-to-text/realtime/event-reference",
        "markers": ("partial_transcript", "committed_transcript", "input_audio_chunk"),
    },
)


def fetch_page(url: str, timeout: float = 10.0) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "UX-Agent/transcribe-audios docs preflight"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def check_docs(fetcher=fetch_page) -> dict:
    """Fetch every official page and report missing contract markers."""
    results = []
    for doc in DOCS:
        try:
            content = fetcher(doc["url"])
            normalized = re.sub(r"\s+", " ", content).lower()
            missing = [marker for marker in doc["markers"] if marker.lower() not in normalized]
            results.append(
                {
                    "name": doc["name"],
                    "url": doc["url"],
                    "status": "ok" if not missing else "contract_changed",
                    "missing_markers": missing,
                }
            )
        except (OSError, UnicodeError, urllib.error.URLError) as error:
            results.append(
                {
                    "name": doc["name"],
                    "url": doc["url"],
                    "status": "unavailable",
                    "error": str(error),
                }
            )

    failures = [result for result in results if result["status"] != "ok"]
    return {
        "status": "success" if not failures else "warning",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": "official ElevenLabs Speech to Text documentation",
        "pages": results,
        "action": (
            "Review the live docs and update this skill before making ElevenLabs API changes."
            if failures
            else "Continue using the documented Speech to Text contract."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on unavailable or changed docs")
    args = parser.parse_args()
    result = check_docs()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.strict and result["status"] != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
