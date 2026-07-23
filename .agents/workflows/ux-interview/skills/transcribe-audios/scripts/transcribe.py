import argparse
import glob
import json
import os
import random
import re
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from elevenlabs.client import ElevenLabs
except ImportError:
    ElevenLabs = None

try:
    from google import genai as google_genai
except ImportError:
    google_genai = None


SUPPORTED_PATTERNS = ("*.mp3", "*.m4a", "*.qta")
DEFAULT_MAX_WORKERS = 5
DEFAULT_MAX_FILE_SIZE_MB = 200
DEFAULT_MAX_RETRIES = 3
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_TRANSCRIPT_PROMPT = """Transcribe this audio file completely and accurately.

Rules:
1. Identify different speakers and label them as "Speaker 1", "Speaker 2", etc.
2. Include timestamps in [MM:SS] format at each speaker change.
3. Format EACH speaker segment on its own line as exactly: [MM:SS] Speaker N: transcribed text
4. Transcribe every word exactly as spoken. Do not summarize, skip, or add commentary.
5. If speakers cannot be distinguished, use "Speaker 1" for everything.
6. Output ONLY the formatted transcription lines, nothing else."""


class TranscriptionError(Exception):
    def __init__(self, code, message, retryable=False, retry_after=None):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after


def get_audio_files(folder_path):
    interview_dir = os.path.join(folder_path, "Interview")
    return sorted(
        path for pattern in SUPPORTED_PATTERNS
        for path in glob.glob(os.path.join(interview_dir, pattern))
    )


def format_timestamp(seconds):
    seconds = max(0, float(seconds or 0))
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def normalize_keyterms(value):
    return [term.strip() for term in (value or "").split(",") if term.strip()] or None


def classify_api_error(error):
    status_code = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    status_code = status_code or getattr(response, "status_code", None)
    headers = getattr(response, "headers", {}) or {}
    retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
    try:
        retry_after = float(retry_after) if retry_after is not None else None
    except (TypeError, ValueError):
        retry_after = None

    if status_code in (400, 401, 403, 404, 413, 422):
        return TranscriptionError("API_REQUEST_ERROR", str(error))
    if status_code == 429 or (status_code is not None and status_code >= 500):
        return TranscriptionError("API_RETRYABLE_ERROR", str(error), True, retry_after)

    message = str(error).lower()
    if any(term in message for term in ("timeout", "connection", "temporar", "rate limit")):
        return TranscriptionError("API_RETRYABLE_ERROR", str(error), True, retry_after)
    return TranscriptionError("API_REQUEST_ERROR", str(error))


def classify_gemini_error(error):
    """Classify a Gemini API error as terminal or retryable."""
    status_code = getattr(error, "code", None) or getattr(error, "status_code", None)
    message = str(error).lower()

    if status_code in (400, 401, 403, 404):
        return TranscriptionError("API_REQUEST_ERROR", str(error))
    if status_code == 429 or (status_code is not None and status_code >= 500):
        return TranscriptionError("API_RETRYABLE_ERROR", str(error), True)

    if any(term in message for term in ("timeout", "connection", "temporar", "rate limit", "resource exhausted", "503", "429")):
        return TranscriptionError("API_RETRYABLE_ERROR", str(error), True)
    return TranscriptionError("API_REQUEST_ERROR", str(error))


def format_transcription(transcription, filename):
    lines = [f"# INTERVIEW TRANSCRIPT: {filename}\n"]
    words = getattr(transcription, "words", None)
    if words:
        current_speaker = None
        current_text = []
        start_time = 0
        for word in words:
            text = str(getattr(word, "text", "")).strip()
            if not text:
                continue
            speaker = getattr(word, "speaker_id", "speaker_0") or "speaker_0"
            if speaker != current_speaker:
                if current_speaker is not None:
                    lines.append(f"**[{format_timestamp(start_time)}] [{current_speaker}]** <br>\n{' '.join(current_text)}\n")
                current_speaker = speaker
                start_time = getattr(word, "start", 0)
                current_text = [text]
            else:
                current_text.append(text)
        if current_speaker is not None and current_text:
            lines.append(f"**[{format_timestamp(start_time)}] [{current_speaker}]** <br>\n{' '.join(current_text)}\n")
    else:
        text = str(getattr(transcription, "text", "")).strip()
        if text:
            lines.append(f"**[00:00] [speaker_0]** <br>\n{text}\n")

    result = "\n".join(lines).strip()
    if result == lines[0].strip():
        raise TranscriptionError("EMPTY_TRANSCRIPT", "The transcription response contained no text.")
    return result


def parse_gemini_response(text, filename):
    """Parse Gemini's transcription response into the standard interview transcript format."""
    lines = [f"# INTERVIEW TRANSCRIPT: {filename}\n"]
    pattern = re.compile(r"\[?(\d{1,2}:\d{2})\]?\s*\[?(Speaker\s*\d+)\]?[:\s]+(.+)", re.IGNORECASE)

    segments = []
    for line in (text or "").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        match = pattern.match(line)
        if match:
            timestamp, speaker, content = match.groups()
            segments.append((timestamp.strip(), speaker.strip(), content.strip()))

    if segments:
        for timestamp, speaker, content in segments:
            lines.append(f"**[{timestamp}] [{speaker}]** <br>\n{content}\n")
    else:
        clean_text = (text or "").strip()
        if clean_text:
            lines.append(f"**[00:00] [Speaker 1]** <br>\n{clean_text}\n")

    result = "\n".join(lines).strip()
    if result == lines[0].strip():
        raise TranscriptionError("EMPTY_TRANSCRIPT", "The Gemini transcription response contained no text.")
    return result


def transcribe_audio(file_path, api_key, keyterms=None, max_retries=DEFAULT_MAX_RETRIES):
    if ElevenLabs is None:
        raise TranscriptionError("MISSING_DEPENDENCY", "The 'elevenlabs' package is required for ElevenLabs transcription. Install with: pip install elevenlabs")
    elevenlabs = ElevenLabs(api_key=api_key)
    for attempt in range(max_retries):
        try:
            with open(file_path, "rb") as audio_file:
                response = elevenlabs.speech_to_text.convert(
                    file=audio_file, model_id="scribe_v2", diarize=True, keyterms=keyterms
                )
            return format_transcription(response, os.path.basename(file_path))
        except TranscriptionError:
            raise
        except Exception as error:
            failure = classify_api_error(error)
            if not failure.retryable or attempt == max_retries - 1:
                raise failure from error
            delay = failure.retry_after if failure.retry_after is not None else 2 ** attempt + random.uniform(0, 0.5)
            time.sleep(delay)


def transcribe_audio_gemini(file_path, api_key, keyterms=None, max_retries=DEFAULT_MAX_RETRIES):
    """Transcribe audio using Google Gemini as a fallback provider."""
    if google_genai is None:
        raise TranscriptionError("MISSING_DEPENDENCY", "The 'google-genai' package is required for Gemini transcription. Install with: pip install google-genai")
    client = google_genai.Client(api_key=api_key)
    ext = os.path.splitext(file_path)[1].lower()
    mime_types = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".qta": "audio/quicktime"}
    mime_type = mime_types.get(ext, "audio/mpeg")

    prompt = GEMINI_TRANSCRIPT_PROMPT
    if keyterms:
        prompt += f"\n7. Pay special attention to these domain-specific terms and transcribe them correctly: {', '.join(keyterms)}"

    uploaded_file = None
    try:
        for attempt in range(max_retries):
            try:
                if uploaded_file is None:
                    uploaded_file = client.files.upload(file=file_path, config={"mime_type": mime_type})
                response = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=[uploaded_file, prompt],
                )
                return parse_gemini_response(response.text, os.path.basename(file_path))
            except TranscriptionError:
                raise
            except Exception as error:
                failure = classify_gemini_error(error)
                if not failure.retryable or attempt == max_retries - 1:
                    raise failure from error
                delay = 2 ** attempt + random.uniform(0, 0.5)
                time.sleep(delay)
    finally:
        if uploaded_file is not None:
            try:
                client.files.delete(name=uploaded_file.name)
            except Exception:
                pass


def is_valid_transcript(path):
    try:
        with open(path, encoding="utf-8") as transcript:
            content = transcript.read()
    except OSError:
        return False
    return content.startswith("# INTERVIEW TRANSCRIPT:") and bool(content.split("\n", 1)[-1].strip())


def atomic_write(path, content):
    directory = os.path.dirname(path)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, delete=False) as temporary:
            temporary.write(content)
            temporary_path = temporary.name
        os.replace(temporary_path, path)
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def process_file(audio_path, folder_path, api_key, keyterms=None, max_file_size_mb=DEFAULT_MAX_FILE_SIZE_MB, max_retries=DEFAULT_MAX_RETRIES, gemini_api_key=None):
    filename = os.path.basename(audio_path)
    base_name, _ = os.path.splitext(filename)
    output_file = os.path.join(folder_path, "Interview", f"transcript_{base_name}.md")
    if os.path.exists(output_file) and is_valid_transcript(output_file):
        return {"status": "skipped", "audio_file": filename, "output_file": output_file}
    try:
        if os.path.getsize(audio_path) > max_file_size_mb * 1024 * 1024:
            raise TranscriptionError("INPUT_TOO_LARGE", f"{filename} exceeds the {max_file_size_mb} MB limit.")

        text = None
        elevenlabs_error = None

        if api_key:
            try:
                text = transcribe_audio(audio_path, api_key, keyterms, max_retries)
            except TranscriptionError as error:
                if gemini_api_key:
                    elevenlabs_error = error
                else:
                    raise

        if text is None and gemini_api_key:
            text = transcribe_audio_gemini(audio_path, gemini_api_key, keyterms, max_retries)

        if text is None:
            raise elevenlabs_error or TranscriptionError("MISSING_API_KEY", "No transcription API key available.")

        atomic_write(output_file, text)
        return {"status": "success", "audio_file": filename, "output_file": output_file}
    except TranscriptionError as error:
        return {"status": "error", "audio_file": filename, "error_code": error.code, "error": str(error)}
    except Exception as error:
        return {"status": "error", "audio_file": filename, "error_code": "FILE_PROCESSING_ERROR", "error": str(error)}


def main():
    parser = argparse.ArgumentParser(description="Transcribe audio files in a folder.")
    parser.add_argument("folder_path")
    parser.add_argument("--keyterms")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    parser.add_argument("--max-file-size-mb", type=int, default=DEFAULT_MAX_FILE_SIZE_MB)
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    args = parser.parse_args()
    if args.max_workers < 1 or args.max_file_size_mb < 1 or args.max_retries < 1:
        parser.error("--max-workers, --max-file-size-mb, and --max-retries must be positive integers.")
    elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not elevenlabs_key and not gemini_key:
        print(json.dumps({"status": "error", "error_code": "MISSING_API_KEY", "message": "Neither ELEVENLABS_API_KEY nor GEMINI_API_KEY is set. At least one is required."}))
        raise SystemExit(1)
    if not os.path.isdir(args.folder_path):
        print(json.dumps({"status": "error", "error_code": "INVALID_INPUT", "message": f"Folder not found: {args.folder_path}"}))
        raise SystemExit(1)
    audio_files = get_audio_files(args.folder_path)
    if not audio_files:
        print(json.dumps({"status": "error", "error_code": "NO_AUDIO_FILES", "message": "No supported audio files found."}))
        raise SystemExit(1)

    results, errors = [], []
    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {executor.submit(process_file, path, args.folder_path, elevenlabs_key, normalize_keyterms(args.keyterms), args.max_file_size_mb, args.max_retries, gemini_key): path for path in audio_files}
        for future in as_completed(futures):
            path = futures[future]
            try:
                result = future.result()
            except Exception as error:
                result = {"status": "error", "audio_file": os.path.basename(path), "error_code": "FUTURE_ERROR", "error": str(error)}
            (results if result["status"] in ("success", "skipped") else errors).append(result)
    results.sort(key=lambda result: result["audio_file"])
    errors.sort(key=lambda result: result["audio_file"])
    if errors:
        print(json.dumps({"status": "error", "error_code": "PARTIAL_FAILURE" if results else "TRANSCRIPTION_FAILED", "message": "One or more files failed to transcribe.", "errors": errors, "successful_transcripts": results}))
        raise SystemExit(1)
    print(json.dumps({"status": "success", "data": {"transcripts": results, "total": len(results)}}))


if __name__ == "__main__":
    main()
