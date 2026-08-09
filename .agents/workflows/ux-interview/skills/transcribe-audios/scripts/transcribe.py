import argparse
from collections import deque
from dataclasses import dataclass, field
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

try:
    from elevenlabs.client import ElevenLabs
except ImportError:
    ElevenLabs = None


SUPPORTED_EXTENSIONS = {
    ".aac",
    ".aiff",
    ".avi",
    ".flac",
    ".flv",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".ogg",
    ".opus",
    ".qt",
    ".qta",
    ".wav",
    ".webm",
    ".wmv",
    ".3gp",
    ".3gpp",
}
DEFAULT_MAX_WORKERS = 5
DEFAULT_MAX_FILE_SIZE_MB = 3072
DEFAULT_MAX_INFLIGHT_MB = 4096
DEFAULT_MAX_RETRIES = 3
DEFAULT_LANGUAGE_CODE = "vi"
METADATA_SCHEMA_VERSION = 1
FINGERPRINT_MODES = ("stat", "sha256")
MARKDOWN_SEGMENT_PATTERN = re.compile(
    r"^\*\*\[(\d+:\d{2}(?::\d{2})?)\]\s+\[([^\]\r\n]+)\]\*\*\s+<br>$"
)


class TranscriptionError(Exception):
    def __init__(self, code, message, retryable=False, retry_after=None, provider=None, attempts=0, warnings=None):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after
        self.provider = provider
        self.attempts = attempts
        self.warnings = warnings or []


@dataclass
class ProviderResponse:
    text: str
    provider: str
    model: str
    attempts: int
    quality: str = "structured"
    warnings: list = field(default_factory=list)


class RequestRateLimiter:
    """Thread-safe ElevenLabs request limiter with a shared backoff window."""

    def __init__(self, requests_per_minute=None):
        self.requests_per_minute = requests_per_minute
        self.request_times = deque()
        self.blocked_until = 0.0
        self.lock = threading.Lock()

    def acquire(self):
        if not self.requests_per_minute:
            return
        while True:
            with self.lock:
                now = time.monotonic()
                while self.request_times and now - self.request_times[0] >= 60:
                    self.request_times.popleft()
                if now < self.blocked_until:
                    delay = self.blocked_until - now
                elif len(self.request_times) < self.requests_per_minute:
                    self.request_times.append(now)
                    return
                else:
                    delay = max(0.01, 60 - (now - self.request_times[0]))
            time.sleep(delay)

    def defer(self, delay):
        if delay is None or delay <= 0:
            return
        with self.lock:
            self.blocked_until = max(self.blocked_until, time.monotonic() + delay)


def get_audio_files(folder_path):
    interview_dir = os.path.join(folder_path, "Interview")
    interview_files = sorted(
        os.path.join(interview_dir, name)
        for name in os.listdir(interview_dir)
        if os.path.isfile(os.path.join(interview_dir, name))
        and os.path.splitext(name)[1].lower() in SUPPORTED_EXTENSIONS
    ) if os.path.isdir(interview_dir) else []
    if interview_files:
        return interview_files
    return sorted(
        os.path.join(folder_path, name)
        for name in os.listdir(folder_path)
        if os.path.isfile(os.path.join(folder_path, name))
        and os.path.splitext(name)[1].lower() in SUPPORTED_EXTENSIONS
    )


def format_timestamp(seconds):
    seconds = max(0, float(seconds or 0))
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def normalize_keyterms(value):
    return [term.strip() for term in (value or "").split(",") if term.strip()] or None


def coerce_status_code(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def classify_api_error(error):
    status_code = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    status_code = coerce_status_code(status_code or getattr(response, "status_code", None))
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


def _iter_transcription_words(transcription):
    """Flatten single-channel and combined/separate multichannel responses."""
    words = getattr(transcription, "words", None)
    if words:
        return list(words)

    transcripts = getattr(transcription, "transcripts", None)
    if isinstance(transcripts, dict):
        flattened = []
        for channel, channel_transcript in transcripts.items():
            for word in getattr(channel_transcript, "words", None) or []:
                if not getattr(word, "speaker_id", None):
                    setattr(word, "speaker_id", f"speaker_{channel}")
                flattened.append(word)
        return sorted(flattened, key=lambda word: float(getattr(word, "start", 0) or 0))
    if isinstance(transcripts, (list, tuple)):
        flattened = []
        for index, channel_transcript in enumerate(transcripts):
            for word in getattr(channel_transcript, "words", None) or []:
                if not getattr(word, "speaker_id", None):
                    setattr(word, "speaker_id", f"speaker_{index}")
                flattened.append(word)
        return sorted(flattened, key=lambda word: float(getattr(word, "start", 0) or 0))
    return []


def format_transcription(transcription, filename):
    lines = [f"# INTERVIEW TRANSCRIPT: {filename}\n"]
    words = _iter_transcription_words(transcription)
    if words:
        current_speaker = None
        current_text = []
        start_time = 0
        for word in words:
            text = str(getattr(word, "text", "")).strip()
            if not text:
                continue
            channel_index = getattr(word, "channel_index", None)
            speaker = getattr(word, "speaker_id", None)
            speaker = speaker or (
                f"speaker_{channel_index}" if channel_index is not None else "speaker_0"
            )
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


def transcribe_audio(
    file_path,
    api_key,
    keyterms=None,
    max_retries=DEFAULT_MAX_RETRIES,
    language_code=DEFAULT_LANGUAGE_CODE,
    tag_audio_events=True,
    num_speakers=None,
    diarization_threshold=None,
    timestamps_granularity="word",
    use_multi_channel=False,
    multichannel_output_style="combined",
    return_result=False,
    rate_limiter=None,
):
    if ElevenLabs is None:
        raise TranscriptionError(
            "MISSING_DEPENDENCY",
            "The 'elevenlabs' package is required for ElevenLabs transcription. Install with: pip install elevenlabs",
            provider="elevenlabs",
        )
    elevenlabs = ElevenLabs(api_key=api_key)
    for attempt in range(max_retries):
        try:
            with open(file_path, "rb") as audio_file:
                if rate_limiter:
                    rate_limiter.acquire()
                response = elevenlabs.speech_to_text.convert(
                    file=audio_file,
                    model_id="scribe_v2",
                    tag_audio_events=tag_audio_events,
                    language_code=language_code,
                    diarize=not use_multi_channel,
                    num_speakers=num_speakers if not use_multi_channel else None,
                    diarization_threshold=(
                        diarization_threshold if not use_multi_channel else None
                    ),
                    timestamps_granularity=timestamps_granularity,
                    no_verbatim=False,
                    keyterms=keyterms,
                    use_multi_channel=use_multi_channel,
                    multichannel_output_style=(
                        multichannel_output_style if use_multi_channel else None
                    ),
                )
            result = ProviderResponse(
                text=format_transcription(response, os.path.basename(file_path)),
                provider="elevenlabs",
                model="scribe_v2",
                attempts=attempt + 1,
            )
            return result if return_result else result.text
        except TranscriptionError as error:
            error.provider = error.provider or "elevenlabs"
            error.attempts = max(error.attempts, attempt + 1)
            raise
        except Exception as error:
            failure = classify_api_error(error)
            failure.provider = "elevenlabs"
            failure.attempts = attempt + 1
            if not failure.retryable or attempt == max_retries - 1:
                raise failure from error
            delay = failure.retry_after if failure.retry_after is not None else 2 ** attempt + random.uniform(0, 0.5)
            if rate_limiter:
                rate_limiter.defer(delay)
            time.sleep(delay)


def is_valid_transcript(path, expected_filename=None):
    try:
        with open(path, encoding="utf-8") as transcript:
            lines = transcript.read().splitlines()
    except OSError:
        return False
    if not lines or not lines[0].startswith("# INTERVIEW TRANSCRIPT: "):
        return False
    if expected_filename and lines[0] != f"# INTERVIEW TRANSCRIPT: {expected_filename}":
        return False

    saw_segment = False
    expecting_content = False
    for raw_line in lines[1:]:
        line = raw_line.strip()
        if not line:
            continue
        if MARKDOWN_SEGMENT_PATTERN.fullmatch(line):
            if expecting_content:
                return False
            saw_segment = True
            expecting_content = True
            continue
        if expecting_content:
            expecting_content = False
            continue
        return False
    return saw_segment and not expecting_content


def get_output_paths(audio_path, folder_path=None):
    filename = os.path.basename(audio_path)
    base_name, _ = os.path.splitext(filename)
    output_dir = os.path.dirname(audio_path)
    if folder_path:
        interview_dir = os.path.join(folder_path, "Interview")
        if os.path.isdir(interview_dir):
            output_dir = interview_dir
    output_file = os.path.join(output_dir, f"transcript_{base_name}.md")
    return output_file, os.path.join(output_dir, f"transcript_{base_name}.meta.json")


def build_source_fingerprint(path, mode="stat"):
    stat_result = os.stat(path)
    fingerprint = {
        "mode": mode,
        "size_bytes": stat_result.st_size,
        "mtime_ns": stat_result.st_mtime_ns,
    }
    if mode == "sha256":
        digest = hashlib.sha256()
        with open(path, "rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        fingerprint["sha256"] = digest.hexdigest()
    return fingerprint


def read_transcript_metadata(path):
    try:
        with open(path, encoding="utf-8") as metadata_file:
            metadata = json.load(metadata_file)
    except (OSError, json.JSONDecodeError):
        return None
    return metadata if isinstance(metadata, dict) else None


def metadata_matches_source(metadata, fingerprint):
    return bool(
        metadata
        and metadata.get("schema_version") == METADATA_SCHEMA_VERSION
        and metadata.get("source_fingerprint") == fingerprint
    )


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


def atomic_write_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def probe_media_duration_seconds(path):
    """Return duration via ffprobe when it is available; otherwise return None."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        completed = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if completed.returncode != 0:
            return None
        duration = float(completed.stdout.strip())
        return duration if duration >= 0 else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def load_pricing(path):
    try:
        with open(path, encoding="utf-8") as pricing_file:
            pricing = json.load(pricing_file)
    except (OSError, json.JSONDecodeError) as error:
        raise TranscriptionError("INVALID_INPUT", f"Could not read pricing JSON: {error}") from error

    providers = pricing.get("providers") if isinstance(pricing, dict) else None
    if not isinstance(providers, dict):
        raise TranscriptionError("INVALID_INPUT", "Pricing JSON must contain a 'providers' object.")
    normalized = {}
    for provider, values in providers.items():
        try:
            rate = float(values["usd_per_minute"])
        except (KeyError, TypeError, ValueError) as error:
            raise TranscriptionError(
                "INVALID_INPUT",
                f"Pricing for '{provider}' must include a non-negative usd_per_minute value.",
            ) from error
        if rate < 0:
            raise TranscriptionError("INVALID_INPUT", f"Pricing for '{provider}' cannot be negative.")
        normalized[provider] = rate
    return {
        "version": pricing.get("version", "unspecified"),
        "providers": normalized,
    }


def estimate_cost_usd(duration_seconds, pricing, providers):
    if duration_seconds is None or not pricing:
        return None
    try:
        return round(sum(pricing["providers"][provider] * duration_seconds / 60 for provider in providers), 6)
    except KeyError as error:
        raise TranscriptionError("INVALID_INPUT", f"Pricing is missing a rate for '{error.args[0]}'.") from error


def coerce_provider_response(value, provider, model, attempts):
    if isinstance(value, ProviderResponse):
        return value
    return ProviderResponse(text=value, provider=provider, model=model, attempts=attempts)


def process_file(
    audio_path,
    folder_path,
    api_key,
    keyterms=None,
    max_file_size_mb=DEFAULT_MAX_FILE_SIZE_MB,
    max_retries=DEFAULT_MAX_RETRIES,
    language_code=DEFAULT_LANGUAGE_CODE,
    tag_audio_events=True,
    num_speakers=None,
    diarization_threshold=None,
    timestamps_granularity="word",
    use_multi_channel=False,
    multichannel_output_style="combined",
    source_fingerprint_mode="stat",
    rate_limiter=None,
    audio_duration_seconds=None,
    pricing=None,
):
    filename = os.path.basename(audio_path)
    output_file, metadata_file = get_output_paths(audio_path, folder_path)
    try:
        source_fingerprint = build_source_fingerprint(audio_path, source_fingerprint_mode)
        existing_metadata = read_transcript_metadata(metadata_file)
        if (
            os.path.exists(output_file)
            and is_valid_transcript(output_file, filename)
            and metadata_matches_source(existing_metadata, source_fingerprint)
        ):
            return {
                "status": "skipped",
                "audio_file": filename,
                "output_file": output_file,
                "metadata_file": metadata_file,
                "provider": existing_metadata.get("provider"),
                "model": existing_metadata.get("model"),
                "attempts": existing_metadata.get("attempts", {}),
                "audio_duration_seconds": existing_metadata.get("audio_duration_seconds"),
                "estimated_cost_usd": existing_metadata.get("estimated_cost_usd"),
                "warnings": existing_metadata.get("warnings", []),
            }
        if os.path.getsize(audio_path) > max_file_size_mb * 1024 * 1024:
            raise TranscriptionError("INPUT_TOO_LARGE", f"{filename} exceeds the {max_file_size_mb} MB limit.")

        response = transcribe_audio(
            audio_path,
            api_key,
            keyterms,
            max_retries,
            language_code,
            tag_audio_events,
            num_speakers,
            diarization_threshold,
            timestamps_granularity,
            use_multi_channel,
            multichannel_output_style,
            return_result=True,
            rate_limiter=rate_limiter,
        )
        provider_response = coerce_provider_response(response, "elevenlabs", "scribe_v2", 1)
        attempts = {"elevenlabs": provider_response.attempts}
        estimated_cost = estimate_cost_usd(audio_duration_seconds, pricing, ["elevenlabs"])
        metadata = {
            "schema_version": METADATA_SCHEMA_VERSION,
            "source_file": filename,
            "source_fingerprint": source_fingerprint,
            "provider": provider_response.provider,
            "model": provider_response.model,
            "attempts": attempts,
            "quality": provider_response.quality,
            "warnings": provider_response.warnings,
            "audio_duration_seconds": audio_duration_seconds,
            "estimated_cost_usd": estimated_cost,
            "pricing_version": pricing.get("version") if pricing else None,
            "created_at": time.time(),
        }
        atomic_write(output_file, provider_response.text)
        atomic_write_json(metadata_file, metadata)
        return {
            "status": "success",
            "audio_file": filename,
            "output_file": output_file,
            "metadata_file": metadata_file,
            "provider": provider_response.provider,
            "model": provider_response.model,
            "attempts": attempts,
            "quality": provider_response.quality,
            "warnings": provider_response.warnings,
            "audio_duration_seconds": audio_duration_seconds,
            "estimated_cost_usd": estimated_cost,
            "pricing_version": metadata["pricing_version"],
        }
    except TranscriptionError as error:
        return {
            "status": "error",
            "audio_file": filename,
            "error_code": error.code,
            "error": str(error),
            "provider": error.provider,
            "attempts": {error.provider: error.attempts} if error.provider else {},
            "warnings": error.warnings,
        }
    except Exception as error:
        return {"status": "error", "audio_file": filename, "error_code": "FILE_PROCESSING_ERROR", "error": str(error)}


def emit_error_and_exit(code, message, **details):
    payload = {"status": "error", "error_code": code, "message": message}
    payload.update({key: value for key, value in details.items() if value is not None})
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(1)


def prepare_pricing_and_durations(audio_files, pricing_file, max_estimated_cost_usd):
    if not pricing_file and max_estimated_cost_usd is not None:
        raise TranscriptionError("INVALID_INPUT", "--max-estimated-cost-usd requires --pricing-json-file.")
    if not pricing_file:
        return None, {path: probe_media_duration_seconds(path) for path in audio_files}

    pricing = load_pricing(pricing_file)
    durations = {path: probe_media_duration_seconds(path) for path in audio_files}
    if max_estimated_cost_usd is None:
        return pricing, durations

    total_estimate = 0.0
    for path, duration in durations.items():
        if duration is None:
            raise TranscriptionError(
                "DURATION_PROBE_FAILED",
                f"Could not determine duration for {os.path.basename(path)}. Install ffprobe or remove the cost budget.",
            )
        total_estimate += estimate_cost_usd(
            duration,
            pricing,
            ["elevenlabs"],
        ) or 0
    if total_estimate > max_estimated_cost_usd:
        raise TranscriptionError(
            "COST_BUDGET_EXCEEDED",
            f"Worst-case estimated batch cost ${total_estimate:.6f} exceeds the ${max_estimated_cost_usd:.6f} budget.",
        )
    return pricing, durations


def run_bounded_batch(
    audio_files,
    folder_path,
    elevenlabs_key,
    args,
    pricing,
    durations,
):
    """Submit only work that fits both worker and aggregate-byte limits."""
    pending = deque()
    for path in audio_files:
        try:
            size_bytes = os.path.getsize(path)
        except OSError:
            size_bytes = 0
        pending.append((path, size_bytes))

    keyterms = normalize_keyterms(args.keyterms)
    rate_limiter = RequestRateLimiter(args.requests_per_minute)
    max_inflight_bytes = args.max_inflight_mb * 1024 * 1024
    results, errors, active = [], [], {}
    active_bytes = 0

    def submit(executor, path, size_bytes):
        return executor.submit(
            process_file,
            path,
            folder_path,
            elevenlabs_key,
            keyterms,
            args.max_file_size_mb,
            args.max_retries,
            args.language_code,
            not args.no_tag_audio_events,
            args.num_speakers,
            args.diarization_threshold,
            args.timestamps_granularity,
            args.use_multi_channel,
            args.multichannel_output_style,
            args.source_fingerprint,
            rate_limiter,
            durations.get(path),
            pricing,
        )

    with ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        while pending or active:
            while pending and len(active) < args.max_workers:
                selected_index = None
                available_bytes = max_inflight_bytes - active_bytes
                for index, (_, size_bytes) in enumerate(pending):
                    if not active or size_bytes <= available_bytes:
                        selected_index = index
                        break
                if selected_index is None:
                    break
                pending.rotate(-selected_index)
                path, size_bytes = pending.popleft()
                pending.rotate(selected_index)
                future = submit(executor, path, size_bytes)
                active[future] = (path, size_bytes)
                active_bytes += size_bytes

            if not active:
                continue

            completed, _ = wait(active, return_when=FIRST_COMPLETED)
            for future in completed:
                path, size_bytes = active.pop(future)
                active_bytes -= size_bytes
                try:
                    result = future.result()
                except Exception as error:
                    result = {
                        "status": "error",
                        "audio_file": os.path.basename(path),
                        "error_code": "FUTURE_ERROR",
                        "error": str(error),
                    }
                (results if result["status"] in ("success", "skipped") else errors).append(result)

    results.sort(key=lambda result: result["audio_file"])
    errors.sort(key=lambda result: result["audio_file"])
    return results, errors


def main():
    parser = argparse.ArgumentParser(description="Transcribe audio files in a folder.")
    parser.add_argument("folder_path")
    parser.add_argument("--keyterms")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    parser.add_argument("--max-file-size-mb", type=int, default=DEFAULT_MAX_FILE_SIZE_MB)
    parser.add_argument("--max-inflight-mb", type=int, default=DEFAULT_MAX_INFLIGHT_MB)
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    parser.add_argument("--requests-per-minute", type=int)
    parser.add_argument("--source-fingerprint", choices=FINGERPRINT_MODES, default="stat")
    parser.add_argument("--pricing-json-file")
    parser.add_argument("--max-estimated-cost-usd", type=float)
    parser.add_argument(
        "--language-code",
        choices=(DEFAULT_LANGUAGE_CODE,),
        default=DEFAULT_LANGUAGE_CODE,
        help="Language is fixed to Vietnamese (vi) for this workflow",
    )
    parser.add_argument("--num-speakers", type=int, choices=range(1, 33))
    parser.add_argument("--diarization-threshold", type=float)
    parser.add_argument(
        "--no-tag-audio-events",
        action="store_true",
        help="Disable ElevenLabs audio-event tags such as laughter or applause",
    )
    parser.add_argument(
        "--timestamps-granularity",
        choices=("none", "word", "character"),
        default="word",
    )
    parser.add_argument("--use-multi-channel", action="store_true")
    parser.add_argument(
        "--multichannel-output-style",
        choices=("separate", "combined"),
        default="combined",
    )
    args = parser.parse_args()
    if (
        args.max_workers < 1
        or args.max_file_size_mb < 1
        or args.max_inflight_mb < 1
        or args.max_retries < 1
        or (args.requests_per_minute is not None and args.requests_per_minute < 1)
        or (args.max_estimated_cost_usd is not None and args.max_estimated_cost_usd < 0)
    ):
        emit_error_and_exit(
            "INVALID_INPUT",
            "Worker, file-size, in-flight, retry, request-rate, and cost-limit values must be positive.",
        )
    if args.diarization_threshold is not None and not 0.1 <= args.diarization_threshold <= 0.4:
        emit_error_and_exit("INVALID_INPUT", "--diarization-threshold must be between 0.1 and 0.4.")
    if args.use_multi_channel and (args.num_speakers is not None or args.diarization_threshold is not None):
        emit_error_and_exit(
            "INVALID_INPUT",
            "--num-speakers and --diarization-threshold cannot be used with --use-multi-channel.",
    )
    elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY")
    if not elevenlabs_key:
        emit_error_and_exit("MISSING_API_KEY", "ELEVENLABS_API_KEY is required for transcription.")
    if not os.path.isdir(args.folder_path):
        emit_error_and_exit("INVALID_INPUT", f"Folder not found: {args.folder_path}")
    audio_files = get_audio_files(args.folder_path)
    if not audio_files:
        emit_error_and_exit("NO_AUDIO_FILES", "No supported audio files found.")

    try:
        pricing, durations = prepare_pricing_and_durations(
            audio_files,
            args.pricing_json_file,
            args.max_estimated_cost_usd,
        )
    except TranscriptionError as error:
        emit_error_and_exit(error.code, str(error))

    results, errors = run_bounded_batch(
        audio_files,
        args.folder_path,
        elevenlabs_key,
        args,
        pricing,
        durations,
    )
    if errors:
        print(json.dumps({"status": "error", "error_code": "PARTIAL_FAILURE" if results else "TRANSCRIPTION_FAILED", "message": "One or more files failed to transcribe.", "errors": errors, "successful_transcripts": results}))
        raise SystemExit(1)
    print(json.dumps({"status": "success", "data": {"transcripts": results, "total": len(results)}}))


if __name__ == "__main__":
    main()
