#!/usr/bin/env python3
"""Deterministic PDF-to-Markdown pipeline for the Codex skill.

Docling owns PDF extraction and document structure. The host agent's built-in
AI owns title confirmation, language classification, and source-completeness
audit. Those AI handoffs are file based in CLI mode and injectable in Python
tests; this module never reads `.env` and never imports an external LLM SDK.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import ipaddress
import json
import os
import re
import shutil
import socket
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union


SKILL_VERSION = "2.1.0"
SCHEMA_VERSION = 2
MANIFEST_SCHEMA_VERSION = "converter-manifest-v2"
MAX_PDF_BYTES = 100 * 1024 * 1024
MAX_COLLECTION_BYTES = 5 * 1024 * 1024
MAX_REMOTE_PDFS = 50
DEFAULT_MAX_PAGE_COUNT = 500
DEFAULT_MAX_STAGING_BYTES = 1024 * 1024 * 1024
DEFAULT_AUDIT_ITEMS_PER_CHUNK = 160
DEFAULT_AUDIT_CHARS_PER_CHUNK = 32_000
DEFAULT_MAX_AUDIT_CHUNKS = 100
REMOTE_MAX_ATTEMPTS = 3
REMOTE_RETRY_BASE_SECONDS = 0.25
MIN_TITLE_CONFIDENCE = 0.85
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
GENERIC_HEADINGS = {
    "abstract",
    "introduction",
    "research article",
    "original article",
    "review article",
    "contents",
    "table of contents",
    "tóm tắt",
    "giới thiệu",
}
WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *("COM%d" % number for number in range(1, 10)),
    *("LPT%d" % number for number in range(1, 10)),
}


class SkillError(RuntimeError):
    """Stable, serializable skill failure."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": "error",
            "error_code": self.code,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class SourceRecord:
    original_location: str
    local_path: str
    source_kind: str
    sha256: str
    original_name: str
    request_url_path: Optional[str] = None


@dataclass(frozen=True)
class ResourceBudget:
    """Fail-closed resource limits for a single paper."""

    max_pdf_bytes: int = MAX_PDF_BYTES
    max_page_count: int = DEFAULT_MAX_PAGE_COUNT
    max_staging_bytes: int = DEFAULT_MAX_STAGING_BYTES
    audit_items_per_chunk: int = DEFAULT_AUDIT_ITEMS_PER_CHUNK
    audit_chars_per_chunk: int = DEFAULT_AUDIT_CHARS_PER_CHUNK
    max_audit_chunks: int = DEFAULT_MAX_AUDIT_CHUNKS

    def validate(self) -> "ResourceBudget":
        values = asdict(self)
        invalid = {name: value for name, value in values.items() if not isinstance(value, int) or value <= 0}
        if invalid:
            raise SkillError("INVALID_INPUT", "Resource-budget values must be positive integers.", invalid=invalid)
        return self


@dataclass
class PreflightBundle:
    candidates: List[Dict[str, Any]]
    selected_candidate: Optional[Dict[str, Any]]
    first_page_image: Optional[str]
    docling_version: str
    conversion_status: str
    page_count: int = 0
    page_count_complete: bool = False


@dataclass
class ConversionBundle:
    conversion_status: str
    docling_version: str
    page_count: int
    asset_inventory: List[Dict[str, Any]]
    normalized_inventory: Dict[str, Any]
    warnings: List[str]
    pipeline_mode: str = "standard_hybrid_ocr"
    progress_events: List[Dict[str, Any]] = field(default_factory=list)


class _PdfLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href and urllib.parse.urlparse(href).path.lower().endswith(".pdf"):
            self.links.append(href)


class UrllibHttpClient:
    """Bounded public HTTP reader with streaming downloads and safe retries."""

    def __init__(
        self,
        *,
        max_attempts: int = REMOTE_MAX_ATTEMPTS,
        retry_base_seconds: float = REMOTE_RETRY_BASE_SECONDS,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.max_attempts = max(1, int(max_attempts))
        self.retry_base_seconds = max(0.0, float(retry_base_seconds))
        self.sleep_fn = sleep_fn

    @staticmethod
    def _is_retryable(exc: BaseException) -> bool:
        if isinstance(exc, SkillError):
            return exc.code == "REMOTE_FETCH_TRANSIENT"
        if isinstance(exc, urllib.error.HTTPError):
            return exc.code == 429 or 500 <= exc.code <= 599
        return isinstance(exc, (urllib.error.URLError, TimeoutError, ConnectionError, socket.timeout))

    def _request(
        self,
        url: str,
        max_bytes: int,
        *,
        destination: Optional[Path] = None,
    ) -> Tuple[str, str, Union[bytes, Tuple[str, int]]]:
        last_error: Optional[BaseException] = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                _reject_unsafe_remote_host(url)
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "convert-researchpaper-to-md/%s" % SKILL_VERSION},
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    final_url = response.geturl()
                    _reject_unsafe_remote_host(final_url)
                    content_type = response.headers.get_content_type()
                    length = response.headers.get("Content-Length")
                    if length and int(length) > max_bytes:
                        raise SkillError(
                            "REMOTE_TOO_LARGE",
                            "Remote response exceeds the configured size limit.",
                            url=url,
                            max_bytes=max_bytes,
                            content_length=int(length),
                        )
                    digest = hashlib.sha256()
                    total = 0
                    prefix = bytearray()
                    effective_limit = max_bytes
                    chunks: List[bytes] = []
                    handle = None
                    try:
                        if destination is not None:
                            destination.parent.mkdir(parents=True, exist_ok=True)
                            handle = destination.open("wb")
                        while True:
                            chunk = response.read(min(1024 * 1024, max_bytes - total + 1))
                            if not chunk:
                                break
                            total += len(chunk)
                            if len(prefix) < 5:
                                prefix.extend(chunk[: 5 - len(prefix)])
                                if len(prefix) == 5 and bytes(prefix) != b"%PDF-" and content_type != "application/pdf":
                                    effective_limit = min(max_bytes, MAX_COLLECTION_BYTES)
                            if total > effective_limit:
                                raise SkillError(
                                    "REMOTE_TOO_LARGE",
                                    "Remote response exceeds the configured size limit.",
                                    url=url,
                                    max_bytes=effective_limit,
                                )
                            digest.update(chunk)
                            if handle is not None:
                                handle.write(chunk)
                            else:
                                chunks.append(chunk)
                    finally:
                        if handle is not None:
                            handle.close()
                    payload: Union[bytes, Tuple[str, int]]
                    payload = (digest.hexdigest(), total) if destination is not None else b"".join(chunks)
                    return final_url, content_type, payload
            except Exception as exc:
                if destination is not None and destination.exists():
                    destination.unlink()
                if isinstance(exc, SkillError) and not self._is_retryable(exc):
                    raise
                if not self._is_retryable(exc):
                    raise SkillError("REMOTE_FETCH_FAILED", "Unable to fetch remote input.", url=url, reason=str(exc), attempts=attempt)
                last_error = exc
                if attempt < self.max_attempts:
                    self.sleep_fn(self.retry_base_seconds * (2 ** (attempt - 1)))
        raise SkillError(
            "REMOTE_FETCH_FAILED",
            "Remote input remained unavailable after bounded retries.",
            url=url,
            reason=str(last_error),
            attempts=self.max_attempts,
            retryable=True,
        )

    def fetch(self, url: str, max_bytes: int) -> Tuple[str, str, bytes]:
        final_url, content_type, payload = self._request(url, max_bytes)
        assert isinstance(payload, bytes)
        return final_url, content_type, payload

    def fetch_to_path(self, url: str, max_bytes: int, destination: Path) -> Tuple[str, str, str, int]:
        final_url, content_type, payload = self._request(url, max_bytes, destination=destination)
        assert isinstance(payload, tuple)
        digest, size = payload
        return final_url, content_type, digest, size


def workspace_root_from_script() -> Path:
    return Path(__file__).resolve().parents[6]


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _reject_unsafe_remote_host(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SkillError("UNSUPPORTED_URL", "Only public HTTP(S) URLs are supported.", url=url)
    if parsed.username or parsed.password:
        raise SkillError("REMOTE_HOST_BLOCKED", "URLs containing credentials are not allowed.", url=url)
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise SkillError("REMOTE_HOST_BLOCKED", "Localhost URLs are not allowed.", url=url)
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, parsed.port or 443)}
    except socket.gaierror as exc:
        raise SkillError("REMOTE_FETCH_TRANSIENT", "Remote hostname could not be resolved yet.", url=url, reason=str(exc))
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise SkillError("REMOTE_HOST_BLOCKED", "Private or local network targets are not allowed.", url=url)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".%s.%s.tmp" % (path.name, uuid.uuid4().hex))
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(str(temporary), str(path))
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SkillError("INVALID_AI_RESPONSE", "JSON input is missing or malformed.", path=str(path), reason=str(exc))
    if not isinstance(value, dict):
        raise SkillError("INVALID_AI_RESPONSE", "JSON input must contain an object.", path=str(path))
    return value


def validate_pdf(path: Path) -> str:
    if path.is_symlink():
        raise SkillError("UNSAFE_PATH", "Symbolic-link PDF inputs are rejected.", path=str(path))
    if not path.is_file() or not os.access(str(path), os.R_OK):
        raise SkillError("INVALID_PDF", "PDF input is not a readable regular file.", path=str(path))
    try:
        with path.open("rb") as handle:
            signature = handle.read(5)
    except OSError as exc:
        raise SkillError("INVALID_PDF", "PDF input could not be read.", path=str(path), reason=str(exc))
    if signature != b"%PDF-":
        raise SkillError("INVALID_PDF", "Input does not have a PDF signature.", path=str(path))
    return sha256_file(path)


def _local_pdf_paths(path: Path, root: Path) -> List[Path]:
    if not path.is_absolute():
        raise SkillError("INVALID_INPUT", "Local url_path must be absolute.", url_path=str(path))
    resolved = path.resolve()
    if not _is_relative_to(resolved, root.resolve()):
        raise SkillError("UNSAFE_PATH", "Local input must stay inside the workspace.", path=str(path))
    if path.is_symlink():
        raise SkillError("UNSAFE_PATH", "Symbolic-link inputs are rejected.", path=str(path))
    if path.is_file():
        candidates = [path]
    elif path.is_dir():
        candidates = sorted(
            (entry for entry in path.iterdir() if entry.is_file() and not entry.is_symlink() and entry.suffix.lower() == ".pdf"),
            key=lambda item: unicodedata.normalize("NFC", item.name).casefold(),
        )
    else:
        raise SkillError("INVALID_INPUT", "url_path does not exist or is not a file/directory.", url_path=str(path))
    if not candidates:
        raise SkillError("NO_PDFS_DISCOVERED", "No PDF files were found in the supplied path.", url_path=str(path))
    return candidates


def _safe_remote_basename(url: str) -> str:
    name = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).name or "download.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    stem = safe_title_stem(Path(name).stem, max_bytes=120)
    return stem + ".pdf"


def _persist_remote_pdf(
    url: str,
    data: bytes,
    incoming_root: Path,
    *,
    request_url_path: Optional[str] = None,
) -> SourceRecord:
    if not data.startswith(b"%PDF-"):
        raise SkillError("INVALID_PDF", "Remote content does not have a PDF signature.", url=url)
    digest = sha256_bytes(data)
    target_dir = incoming_root / digest
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / _safe_remote_basename(url)
    if target.exists() and sha256_file(target) != digest:
        raise SkillError("REMOTE_DOWNLOAD_COLLISION", "Remote staging filename collision.", path=str(target))
    if not target.exists():
        temporary = target.with_suffix(".part")
        temporary.write_bytes(data)
        os.replace(str(temporary), str(target))
    return SourceRecord(url, str(target), "remote_pdf", digest, target.name, request_url_path or url)


def _persist_remote_pdf_path(
    url: str,
    downloaded: Path,
    digest: str,
    incoming_root: Path,
    *,
    request_url_path: Optional[str] = None,
) -> SourceRecord:
    try:
        with downloaded.open("rb") as handle:
            signature = handle.read(5)
    except OSError as exc:
        raise SkillError("INVALID_PDF", "Streamed remote content could not be read.", url=url, reason=str(exc))
    if signature != b"%PDF-":
        raise SkillError("INVALID_PDF", "Remote content does not have a PDF signature.", url=url)
    if sha256_file(downloaded) != digest:
        raise SkillError("SOURCE_HASH_MISMATCH", "Streamed remote PDF hash changed before persistence.", url=url)
    target_dir = incoming_root / digest
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / _safe_remote_basename(url)
    if target.exists():
        if sha256_file(target) != digest:
            raise SkillError("REMOTE_DOWNLOAD_COLLISION", "Remote staging filename collision.", path=str(target))
        downloaded.unlink()
    else:
        os.replace(str(downloaded), str(target))
    return SourceRecord(url, str(target), "remote_pdf", digest, target.name, request_url_path or url)


def _fetch_remote_resource(
    client: Any,
    url: str,
    max_bytes: int,
    incoming_root: Path,
) -> Tuple[str, str, Optional[Path], Optional[bytes], str, int]:
    """Fetch to disk when supported; legacy injected clients remain compatible."""

    if hasattr(client, "fetch_to_path"):
        incoming_root.mkdir(parents=True, exist_ok=True)
        temporary = incoming_root / (".download-%s.part" % uuid.uuid4().hex)
        try:
            final_url, content_type, digest, size = client.fetch_to_path(url, max_bytes, temporary)
            return final_url, content_type, temporary, None, digest, int(size)
        except Exception:
            if temporary.exists():
                temporary.unlink()
            raise
    final_url, content_type, data = client.fetch(url, max_bytes)
    return final_url, content_type, None, data, sha256_bytes(data), len(data)


def _directory_size(path: Path) -> int:
    total = 0
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        for item in path.rglob("*"):
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
    return total


def _cleanup_converter_scratch(workspace_root: Path, *paths: Optional[Path]) -> Dict[str, List[str]]:
    """Remove only converter-owned scratch children and report every decision."""

    root = workspace_root.resolve()
    scratch = root / ".agents" / "scratch" / "convert-researchpaper-to-md"
    owned_roots = (scratch / "preflight", scratch / "incoming")
    result: Dict[str, List[str]] = {"removed": [], "retained": []}
    for value in paths:
        if value is None:
            continue
        path = value.resolve()
        owner = next((candidate for candidate in owned_roots if path != candidate and _is_relative_to(path, candidate)), None)
        if owner is None:
            result["retained"].append(str(path))
            continue
        try:
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            result["removed"].append(str(path))
            parent = path.parent
            while parent != owner and _is_relative_to(parent, owner):
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
        except OSError:
            result["retained"].append(str(path))
    return result


def discover_sources(
    url_path: str,
    *,
    workspace_root: Optional[Path] = None,
    http_client: Optional[Any] = None,
    budget: Optional[ResourceBudget] = None,
) -> Dict[str, Any]:
    if not isinstance(url_path, str) or not url_path.strip():
        raise SkillError("INVALID_INPUT", "url_path must be a non-empty string.")
    root = (workspace_root or workspace_root_from_script()).resolve()
    limits = (budget or ResourceBudget()).validate()
    parsed = urllib.parse.urlparse(url_path)

    if parsed.scheme in {"", "file"}:
        raw_path = urllib.request.url2pathname(parsed.path) if parsed.scheme == "file" else url_path
        paths = _local_pdf_paths(Path(raw_path), root)
        oversized = [str(path) for path in paths if path.stat().st_size > limits.max_pdf_bytes]
        if oversized:
            raise SkillError(
                "RESOURCE_REVIEW_REQUIRED",
                "A local PDF exceeds the configured source-size budget.",
                paths=oversized,
                max_pdf_bytes=limits.max_pdf_bytes,
            )
        records = [
            SourceRecord(
                url_path,
                str(path.resolve()),
                "file_pdf" if parsed.scheme == "file" else "local_pdf",
                validate_pdf(path),
                path.name,
                url_path,
            )
            for path in paths
        ]
        source_type = "file_directory" if parsed.scheme == "file" and len(paths) > 1 else "local_directory" if len(paths) > 1 else records[0].source_kind
    elif parsed.scheme in {"http", "https"}:
        client = http_client or UrllibHttpClient()
        incoming_root = root / ".agents/scratch/convert-researchpaper-to-md/incoming"
        final_url, content_type, downloaded, data, digest, size = _fetch_remote_resource(
            client, url_path, limits.max_pdf_bytes, incoming_root
        )
        if downloaded is not None:
            with downloaded.open("rb") as handle:
                signature = handle.read(5)
        else:
            signature = (data or b"")[:5]
        if signature == b"%PDF-" or content_type == "application/pdf":
            if downloaded is not None:
                records = [_persist_remote_pdf_path(final_url, downloaded, digest, incoming_root, request_url_path=url_path)]
            else:
                records = [_persist_remote_pdf(final_url, data or b"", incoming_root, request_url_path=url_path)]
            source_type = "remote_pdf"
        else:
            if size > MAX_COLLECTION_BYTES:
                if downloaded is not None and downloaded.exists():
                    downloaded.unlink()
                raise SkillError("REMOTE_TOO_LARGE", "Remote collection page is too large.", url=url_path)
            if downloaded is not None:
                page_data = downloaded.read_bytes()
                downloaded.unlink()
            else:
                page_data = data or b""
            parser = _PdfLinkParser()
            parser.feed(page_data.decode("utf-8", errors="replace"))
            origin = urllib.parse.urlparse(final_url)
            links: List[str] = []
            for href in parser.links:
                absolute = urllib.parse.urljoin(final_url, href)
                target = urllib.parse.urlparse(absolute)
                if target.scheme in {"http", "https"} and target.netloc == origin.netloc and absolute not in links:
                    links.append(absolute)
            if not links:
                raise SkillError("NO_PDFS_DISCOVERED", "No same-origin PDF links were found on the collection page.", url=url_path)
            if len(links) > MAX_REMOTE_PDFS:
                raise SkillError("TOO_MANY_PDFS", "Remote collection exceeds the PDF link limit.", count=len(links), limit=MAX_REMOTE_PDFS)
            records = []
            seen_hashes = set()
            for link in links:
                resolved_url, _mime, pdf_path, pdf_data, pdf_digest, _pdf_size = _fetch_remote_resource(
                    client, link, limits.max_pdf_bytes, incoming_root
                )
                if pdf_path is not None:
                    record = _persist_remote_pdf_path(resolved_url, pdf_path, pdf_digest, incoming_root, request_url_path=url_path)
                else:
                    record = _persist_remote_pdf(resolved_url, pdf_data or b"", incoming_root, request_url_path=url_path)
                if record.sha256 not in seen_hashes:
                    records.append(record)
                    seen_hashes.add(record.sha256)
            source_type = "remote_collection"
    else:
        raise SkillError("UNSUPPORTED_URL", "url_path must be a local path, file:// URL, or HTTP(S) URL.", url_path=url_path)

    return {
        "status": "success",
        "url_path": url_path,
        "source_type": source_type,
        "pdf_count": len(records),
        "sources": [asdict(record) for record in records],
    }


def _normalized_label(value: Any) -> str:
    label = getattr(value, "value", value)
    return str(label or "").strip().lower().replace("-", "_").replace(" ", "_")


def _candidate_allowed(item: Mapping[str, Any]) -> bool:
    text = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
    if not text or len(text) < 5:
        return False
    if _normalized_label(item.get("content_layer")) not in {"", "body"}:
        return False
    lowered = text.casefold().strip(" .:")
    if lowered in GENERIC_HEADINGS:
        return False
    if lowered.startswith(("doi:", "http://", "https://", "issn ")):
        return False
    if len(text) > 500:
        return False
    return True


def select_title_candidate(items: Sequence[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return first BODY TITLE, then first BODY SECTION_HEADER."""
    for wanted in ("title", "section_header"):
        for item in items:
            if _normalized_label(item.get("label")) == wanted and _candidate_allowed(item):
                candidate = dict(item)
                candidate["text"] = re.sub(r"\s+", " ", str(item.get("text"))).strip()
                return candidate
    return None


def safe_title_stem(title: str, max_bytes: int = 180) -> str:
    value = unicodedata.normalize("NFC", str(title or ""))
    value = INVALID_FILENAME_CHARS.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    if not value:
        raise SkillError("INVALID_TITLE", "Validated paper title cannot form a safe filename.")
    if value.upper() in WINDOWS_RESERVED:
        value = "Paper - " + value
    while len(value.encode("utf-8")) > max_bytes:
        value = value[:-1].rstrip(" .")
    if len(value) < 3:
        raise SkillError("INVALID_TITLE", "Validated paper title is too short after filename sanitization.")
    return value


def validate_title_decision(decision: Mapping[str, Any], candidate: Mapping[str, Any]) -> str:
    valid = decision.get("valid") is True
    confidence = decision.get("confidence")
    title = decision.get("title")
    if not valid or not isinstance(confidence, (int, float)) or float(confidence) < MIN_TITLE_CONFIDENCE:
        raise SkillError(
            "TITLE_REVIEW_REQUIRED",
            "Built-in AI did not confirm the first paper heading with sufficient confidence.",
            candidate=candidate.get("text"),
            confidence=confidence,
        )
    if not isinstance(title, str) or not title.strip():
        raise SkillError("INVALID_AI_RESPONSE", "Title decision must include a non-empty title string.")
    return safe_title_stem(title)


def _status_name(status: Any) -> str:
    raw = getattr(status, "name", None) or getattr(status, "value", None) or str(status)
    return str(raw).split(".")[-1].upper()


class DoclingAdapter:
    """Lazy adapter around the currently reviewed Docling 2.x public API."""

    def __init__(
        self,
        image_scale: float = 2.0,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.image_scale = image_scale
        self.progress_callback = progress_callback
        self.progress_events: List[Dict[str, Any]] = []

    def _emit(self, stage: str, percent: int, **details: Any) -> None:
        event = {"stage": stage, "percent": percent, "details": details}
        self.progress_events.append(event)
        if self.progress_callback is not None:
            self.progress_callback(event)

    @staticmethod
    def dependency_report() -> Dict[str, Any]:
        if sys.version_info < (3, 10):
            return {
                "available": False,
                "error_code": "PYTHON_VERSION_UNSUPPORTED",
                "message": "Docling 2.117.0 requires Python 3.10 or newer.",
                "python": sys.version.split()[0],
            }
        try:
            version = importlib.metadata.version("docling")
            importlib.metadata.version("docling-core")
        except importlib.metadata.PackageNotFoundError:
            return {
                "available": False,
                "error_code": "DOCLING_MISSING",
                "message": "Install Docling in the Python 3.10+ runtime before conversion.",
                "install": "python3 -m pip install 'docling>=2.117.0,<3'",
            }
        return {"available": True, "docling_version": version, "python": sys.version.split()[0]}

    def _imports(self) -> Dict[str, Any]:
        report = self.dependency_report()
        if not report.get("available"):
            raise SkillError(str(report["error_code"]), str(report["message"]), dependency_report=report)
        try:
            from docling.datamodel.base_models import ConversionStatus, InputFormat
            from docling.datamodel.pipeline_options import (
                OcrMode,
                PdfPipelineOptions,
                TableStructureOptions,
                TesseractCliOcrOptions,
            )
            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling_core.types.doc import ImageRefMode, PictureItem, TableItem
        except Exception as exc:
            raise SkillError("DOCLING_API_INCOMPATIBLE", "Installed Docling API is incompatible with this skill.", reason=str(exc))
        return {
            "InputFormat": InputFormat,
            "ConversionStatus": ConversionStatus,
            "OcrMode": OcrMode,
            "PdfPipelineOptions": PdfPipelineOptions,
            "TableStructureOptions": TableStructureOptions,
            "TesseractCliOcrOptions": TesseractCliOcrOptions,
            "DocumentConverter": DocumentConverter,
            "PdfFormatOption": PdfFormatOption,
            "ImageRefMode": ImageRefMode,
            "PictureItem": PictureItem,
            "TableItem": TableItem,
            "version": report["docling_version"],
        }

    def _converter(self, api: Mapping[str, Any], full: bool, force_full_page_ocr: bool = False) -> Any:
        # Mirrors Docling's documented custom-conversion and full-page OCR
        # examples: PdfPipelineOptions -> PdfFormatOption -> DocumentConverter.
        options = api["PdfPipelineOptions"]()
        options.do_ocr = True
        options.do_table_structure = True
        options.table_structure_options = api["TableStructureOptions"](do_cell_matching=True)
        options.images_scale = self.image_scale
        options.generate_page_images = True
        options.generate_picture_images = full
        if force_full_page_ocr:
            options.ocr_options = api["TesseractCliOcrOptions"](
                lang=["auto"],
                mode=api["OcrMode"].FULL_PAGE,
            )
        return api["DocumentConverter"](
            format_options={api["InputFormat"].PDF: api["PdfFormatOption"](pipeline_options=options)}
        )

    @staticmethod
    def _needs_full_page_ocr(document: Any) -> bool:
        pages = getattr(document, "pages", {}) or {}
        page_count = len(pages)
        covered_pages = set()
        text_characters = 0
        for item, _level in document.iterate_items():
            text = str(getattr(item, "text", "") or "").strip()
            if not text:
                continue
            text_characters += len(text)
            provenance = getattr(item, "prov", None) or []
            if provenance and getattr(provenance[0], "page_no", None) is not None:
                covered_pages.add(int(provenance[0].page_no))
        if page_count == 0:
            return True
        if text_characters < max(80, page_count * 20):
            return True
        return len(covered_pages) / float(page_count) < 0.6 and text_characters < page_count * 200

    def preflight(self, source: Path, job_dir: Path) -> PreflightBundle:
        self.progress_events = []
        self._emit("docling_preflight_configure", 5, source=str(source), page_range=[1, 3])
        api = self._imports()
        try:
            self._emit("docling_preflight_convert", 15, pipeline="standard_hybrid_ocr")
            result = self._converter(api, full=False).convert(source, page_range=(1, 3))
        except Exception as exc:
            raise SkillError("DOCLING_PREFLIGHT_FAILED", "Docling could not inspect the paper title.", path=str(source), reason=str(exc))
        status = _status_name(result.status)
        if status != "SUCCESS":
            code = "DOCLING_PARTIAL_SUCCESS" if status == "PARTIAL_SUCCESS" else "DOCLING_PREFLIGHT_FAILED"
            raise SkillError(code, "Docling title preflight did not complete successfully.", path=str(source), status=status)

        items: List[Dict[str, Any]] = []
        for order, (item, _level) in enumerate(result.document.iterate_items()):
            provenance = getattr(item, "prov", None) or []
            page_no = getattr(provenance[0], "page_no", None) if provenance else None
            items.append(
                {
                    "order": order,
                    "label": _normalized_label(getattr(item, "label", "")),
                    "content_layer": _normalized_label(getattr(item, "content_layer", "body")),
                    "text": getattr(item, "text", ""),
                    "page_no": page_no,
                    "self_ref": getattr(item, "self_ref", None),
                }
            )
        candidates = [item for item in items if _normalized_label(item.get("label")) in {"title", "section_header"} and _candidate_allowed(item)]
        selected = select_title_candidate(items)
        image_path: Optional[Path] = None
        pages = getattr(result.document, "pages", {}) or {}
        if pages:
            first_key = sorted(pages)[0]
            page = pages[first_key]
            page_image = getattr(getattr(page, "image", None), "pil_image", None)
            if page_image is not None:
                image_path = job_dir / "first-page.png"
                job_dir.mkdir(parents=True, exist_ok=True)
                page_image.save(str(image_path), format="PNG")
        input_page_count = getattr(getattr(result, "input", None), "page_count", None)
        reported_page_count = getattr(result, "page_count", None)
        page_count = input_page_count or reported_page_count or len(pages)
        page_count_complete = bool(input_page_count or reported_page_count)
        self._emit(
            "docling_preflight_complete",
            20,
            status=status,
            candidate_count=len(candidates),
            page_count=int(page_count or 0),
            page_count_complete=page_count_complete,
        )
        return PreflightBundle(
            candidates,
            selected,
            str(image_path) if image_path else None,
            api["version"],
            status,
            int(page_count or 0),
            page_count_complete,
        )

    def convert(self, source: Path, staging_dir: Path) -> ConversionBundle:
        self.progress_events = []
        self._emit("docling_configure", 25, source=str(source), pipeline="standard_hybrid_ocr")
        api = self._imports()
        try:
            self._emit("docling_convert", 35, pipeline="standard_hybrid_ocr")
            result = self._converter(api, full=True).convert(source)
        except Exception as exc:
            raise SkillError("DOCLING_CONVERSION_FAILED", "Docling failed during full conversion.", path=str(source), reason=str(exc))
        status = _status_name(result.status)
        if status != "SUCCESS":
            code = "DOCLING_PARTIAL_SUCCESS" if status == "PARTIAL_SUCCESS" else "DOCLING_CONVERSION_FAILED"
            raise SkillError(code, "Docling full conversion did not complete successfully.", path=str(source), status=status)

        warnings: List[str] = []
        pipeline_mode = "standard_hybrid_ocr"
        if self._needs_full_page_ocr(result.document):
            if shutil.which("tesseract") is None:
                raise SkillError(
                    "OCR_DEPENDENCY_MISSING",
                    "Docling requires its documented Tesseract full-page OCR fallback, but the tesseract executable is unavailable.",
                    install="Install Tesseract CLI and language data, then rerun the paper.",
                )
            try:
                self._emit("docling_full_page_ocr", 50, backend="TesseractCliOcrOptions", lang=["auto"])
                result = self._converter(api, full=True, force_full_page_ocr=True).convert(source)
            except Exception as exc:
                raise SkillError("DOCLING_OCR_FAILED", "Docling full-page OCR fallback failed.", path=str(source), reason=str(exc))
            status = _status_name(result.status)
            if status != "SUCCESS":
                code = "DOCLING_PARTIAL_SUCCESS" if status == "PARTIAL_SUCCESS" else "DOCLING_OCR_FAILED"
                raise SkillError(code, "Docling full-page OCR did not complete successfully.", path=str(source), status=status)
            if self._needs_full_page_ocr(result.document):
                raise SkillError("CONTENT_INCOMPLETE", "Docling full-page OCR still produced insufficient page text coverage.")
            pipeline_mode = "tesseract_full_page_ocr_auto"
            warnings.append("Standard hybrid OCR had insufficient text coverage; used documented Tesseract full-page OCR fallback.")

        staging_dir.mkdir(parents=True, exist_ok=True)
        asset_dir = staging_dir / "Asset"
        asset_dir.mkdir(parents=True, exist_ok=True)
        page_render_dir = staging_dir / "page-renders"
        page_render_dir.mkdir(parents=True, exist_ok=True)
        self._emit("docling_export_page_images", 65, image_scale=self.image_scale)
        page_render_paths: List[str] = []
        for _page_key, page in sorted((getattr(result.document, "pages", {}) or {}).items()):
            page_no = int(getattr(page, "page_no", 0))
            page_image = getattr(getattr(page, "image", None), "pil_image", None)
            if page_image is None:
                raise SkillError("PAGE_RENDER_FAILED", "Docling did not retain a required page image.", page_no=page_no)
            page_path = page_render_dir / ("page-%03d.png" % page_no)
            with page_path.open("wb") as handle:
                page_image.save(handle, format="PNG")
            page_render_paths.append(str(page_path))
        items: List[Dict[str, Any]] = []
        assets: List[Dict[str, Any]] = []
        picture_links: List[str] = []
        figure_count = 0
        table_count = 0
        self._emit("docling_export_elements", 75, image_scale=self.image_scale)
        for order, (item, level) in enumerate(result.document.iterate_items()):
            provenance = getattr(item, "prov", None) or []
            page_no = getattr(provenance[0], "page_no", None) if provenance else None
            label = _normalized_label(getattr(item, "label", ""))
            items.append(
                {
                    "order": order,
                    "level": level,
                    "label": label,
                    "content_layer": _normalized_label(getattr(item, "content_layer", "body")),
                    "text": getattr(item, "text", ""),
                    "page_no": page_no,
                    "self_ref": getattr(item, "self_ref", None),
                }
            )
            try:
                if isinstance(item, api["PictureItem"]):
                    figure_count += 1
                    name = "page-%03d-figure-%03d.png" % (int(page_no or 0), figure_count)
                    image = item.get_image(result.document)
                    if image is None:
                        raise ValueError("Docling returned no picture image")
                    with (asset_dir / name).open("wb") as handle:
                        image.save(handle, format="PNG")
                    picture_links.append(name)
                    assets.append({"path": "Asset/" + name, "kind": "picture", "page_no": page_no, "sha256": sha256_file(asset_dir / name)})
                elif isinstance(item, api["TableItem"]):
                    table_count += 1
                    name = "page-%03d-table-%03d.png" % (int(page_no or 0), table_count)
                    image = item.get_image(result.document)
                    if image is not None:
                        with (asset_dir / name).open("wb") as handle:
                            image.save(handle, format="PNG")
                        assets.append({"path": "Asset/" + name, "kind": "table", "page_no": page_no, "sha256": sha256_file(asset_dir / name)})
            except Exception as exc:
                raise SkillError("ASSET_EXTRACTION_FAILED", "A Docling visual could not be exported.", label=label, page_no=page_no, reason=str(exc))

        try:
            # Follow Docling's documented serialization helper and explicitly
            # request placeholders before mapping them to our Asset filenames.
            docling_markdown = staging_dir / "docling-placeholder.md"
            result.document.save_as_markdown(
                docling_markdown,
                image_mode=api["ImageRefMode"].PLACEHOLDER,
            )
            markdown = docling_markdown.read_text(encoding="utf-8")
            docling_markdown.unlink()
            lossless = result.document.export_to_dict()
        except Exception as exc:
            raise SkillError("DOCLING_SERIALIZATION_FAILED", "Docling document serialization failed.", reason=str(exc))

        for index, asset_name in enumerate(picture_links, start=1):
            link = "![Extracted figure %d](Asset/%s)" % (index, asset_name)
            if "<!-- image -->" in markdown:
                markdown = markdown.replace("<!-- image -->", link, 1)
            else:
                markdown = markdown.rstrip() + "\n\n" + link + "\n"
        if "<!-- image -->" in markdown:
            raise SkillError("ASSET_PARITY_FAILED", "Docling Markdown contains unresolved image placeholders.")
        if not markdown.strip():
            raise SkillError("CONTENT_INCOMPLETE", "Docling produced empty Markdown.")

        atomic_write_text(staging_dir / "original.md", markdown.rstrip() + "\n")
        normalized_inventory = {
            "page_count": len(getattr(result.document, "pages", {}) or {}),
            "page_renders": page_render_paths,
            "items": items,
            "asset_count": len(assets),
            "pipeline_mode": pipeline_mode,
        }
        atomic_write_json(staging_dir / "lossless-docling.json", {"docling": lossless, "normalized": normalized_inventory})
        self._emit("docling_complete", 90, status=status, pipeline=pipeline_mode, assets=len(assets))
        return ConversionBundle(
            status,
            api["version"],
            normalized_inventory["page_count"],
            assets,
            normalized_inventory,
            warnings,
            pipeline_mode,
            list(self.progress_events),
        )


def run_preflight(
    source: SourceRecord,
    *,
    docling_engine: Optional[Any] = None,
    workspace_root: Optional[Path] = None,
) -> Dict[str, Any]:
    root = (workspace_root or workspace_root_from_script()).resolve()
    path = Path(source.local_path).resolve()
    current_hash = validate_pdf(path)
    if current_hash != source.sha256:
        raise SkillError("SOURCE_CHANGED", "PDF changed after discovery; restart the conversion.", path=str(path))
    job_dir = root / ".agents/scratch/convert-researchpaper-to-md/preflight" / (source.sha256[:12] + "-" + uuid.uuid4().hex[:8])
    try:
        bundle = (docling_engine or DoclingAdapter()).preflight(path, job_dir)
        if not bundle.selected_candidate:
            raise SkillError("TITLE_NOT_FOUND", "Docling found no reliable first paper heading.", path=str(path), candidates=bundle.candidates)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "source": asdict(source),
            "job_dir": str(job_dir),
            "candidates": bundle.candidates,
            "selected_candidate": bundle.selected_candidate,
            "first_page_image": bundle.first_page_image,
            "docling_version": bundle.docling_version,
            "conversion_status": bundle.conversion_status,
            "page_count": bundle.page_count,
            "page_count_complete": bundle.page_count_complete,
            "title_ai_request": {
                "task": "Confirm the first true research-paper title using the candidate and first-page render.",
                "response_schema": {"valid": "boolean", "confidence": "number 0..1", "title": "string", "reason": "string"},
            },
        }
        preflight_path = job_dir / "preflight.json"
        atomic_write_json(preflight_path, payload)
        payload["preflight_path"] = str(preflight_path)
        return payload
    except Exception:
        _cleanup_converter_scratch(root, job_dir)
        raise


def _load_manifest(output_dir: Path) -> Optional[Dict[str, Any]]:
    manifest = output_dir / ".conversion-manifest.json"
    if not manifest.is_file():
        return None
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _manifest_is_valid(output_dir: Path, source_hash: str) -> bool:
    manifest = _load_manifest(output_dir)
    if (
        not manifest
        or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or manifest.get("source_sha256") != source_hash
        or manifest.get("status") != "success"
    ):
        return False
    artifacts = manifest.get("artifact_hashes")
    if not isinstance(artifacts, dict):
        return False
    for relative, expected in artifacts.items():
        path = output_dir / relative
        if not path.is_file() or sha256_file(path) != expected:
            return False
    return True


def _choose_rename_target(source: Path, parent: Path, stem: str, digest: str) -> Path:
    candidate = parent / (stem + ".pdf")
    try:
        if candidate.exists() and source.samefile(candidate):
            return candidate
    except OSError:
        pass
    if not candidate.exists() and not candidate.with_suffix("").exists():
        return candidate
    if candidate.exists() and sha256_file(candidate) == digest:
        raise SkillError("DUPLICATE_PDF", "A PDF with the validated title and identical content already exists.", path=str(candidate))
    suffix = "--" + digest[:8]
    for number in range(1, 1000):
        extra = suffix if number == 1 else suffix + "-%d" % number
        alternative = parent / (stem + extra + ".pdf")
        if not alternative.exists() and not alternative.with_suffix("").exists():
            return alternative
    raise SkillError("RENAME_COLLISION", "Unable to choose a collision-free title filename.", title=stem)


def _rename_source(source: Path, target: Path, expected_hash: str) -> Tuple[Path, bool]:
    try:
        if source == target or (target.exists() and source.samefile(target)):
            renamed = False
        else:
            if not target.parent.is_dir():
                raise FileNotFoundError("rename target parent does not exist: %s" % target.parent)
            os.replace(str(source), str(target))
            renamed = True
    except Exception as exc:
        raise SkillError("SOURCE_RENAME_FAILED", "The PDF could not be renamed to its validated paper title.", source=str(source), target=str(target), reason=str(exc))
    if sha256_file(target) != expected_hash:
        raise SkillError("SOURCE_HASH_MISMATCH", "Renamed PDF hash does not match the discovered source.", path=str(target))
    return target, renamed


def _enforce_preflight_budget(source_path: Path, preflight: Mapping[str, Any], limits: ResourceBudget) -> None:
    source_bytes = source_path.stat().st_size
    if source_bytes > limits.max_pdf_bytes:
        raise SkillError(
            "RESOURCE_REVIEW_REQUIRED",
            "The PDF exceeds the configured source-size budget.",
            source_bytes=source_bytes,
            max_pdf_bytes=limits.max_pdf_bytes,
        )
    page_count = int(preflight.get("page_count") or 0)
    if preflight.get("page_count_complete") is True and page_count > limits.max_page_count:
        raise SkillError(
            "RESOURCE_REVIEW_REQUIRED",
            "The PDF exceeds the configured page-count budget before full conversion.",
            page_count=page_count,
            max_page_count=limits.max_page_count,
        )


def _build_source_audit_plan(
    staging_dir: Path,
    conversion: ConversionBundle,
    limits: ResourceBudget,
) -> Dict[str, Any]:
    items = list(conversion.normalized_inventory.get("items") or [])
    chunks: List[Dict[str, Any]] = []
    current: List[Mapping[str, Any]] = []
    current_chars = 0

    def flush() -> None:
        nonlocal current, current_chars
        if not current and chunks:
            return
        chunk_items = current or [{}]
        pages = sorted({int(item["page_no"]) for item in chunk_items if item.get("page_no") is not None})
        chunk_id = "source-audit-%04d" % (len(chunks) + 1)
        chunks.append(
            {
                "chunk_id": chunk_id,
                "item_ids": [str(item.get("self_ref") or item.get("order")) for item in current],
                "item_order_start": current[0].get("order") if current else None,
                "item_order_end": current[-1].get("order") if current else None,
                "page_numbers": pages,
                "item_count": len(current),
                "text_characters": current_chars,
            }
        )
        current = []
        current_chars = 0

    for item in items:
        item_chars = len(str(item.get("text") or ""))
        if current and (
            len(current) >= limits.audit_items_per_chunk
            or current_chars + item_chars > limits.audit_chars_per_chunk
        ):
            flush()
        current.append(item)
        current_chars += item_chars
    flush()
    if len(chunks) > limits.max_audit_chunks:
        raise SkillError(
            "RESOURCE_REVIEW_REQUIRED",
            "The source audit exceeds the configured chunk budget.",
            audit_chunk_count=len(chunks),
            max_audit_chunks=limits.max_audit_chunks,
        )
    original = staging_dir / "original.md"
    inventory = staging_dir / "lossless-docling.json"
    plan = {
        "schema_version": "source-audit-plan-v1",
        "chunk_count": len(chunks),
        "chunk_ids": [chunk["chunk_id"] for chunk in chunks],
        "original_md": {"path": str(original), "sha256": sha256_file(original)},
        "lossless_inventory": {"path": str(inventory), "sha256": sha256_file(inventory)},
        "page_count": conversion.page_count,
        "chunks": chunks,
        "final_synthesis_required": True,
    }
    plan_path = staging_dir / "source-audit-plan.json"
    atomic_write_json(plan_path, plan)
    plan["path"] = str(plan_path)
    plan["sha256"] = sha256_file(plan_path)
    return plan


def _prepare_paper_impl(
    preflight: Mapping[str, Any],
    title_decision: Mapping[str, Any],
    *,
    output_root: Optional[Path] = None,
    force: bool = False,
    docling_engine: Optional[Any] = None,
    workspace_root: Optional[Path] = None,
    budget: Optional[ResourceBudget] = None,
) -> Dict[str, Any]:
    source_data = preflight.get("source")
    candidate = preflight.get("selected_candidate")
    if not isinstance(source_data, dict) or not isinstance(candidate, dict):
        raise SkillError("INVALID_PREFLIGHT", "Preflight data is missing its source or title candidate.")
    source = SourceRecord(**source_data)
    source_path = Path(source.local_path).resolve()
    if validate_pdf(source_path) != source.sha256:
        raise SkillError("SOURCE_CHANGED", "PDF changed after title preflight; restart the conversion.", path=str(source_path))
    limits = (budget or ResourceBudget()).validate()
    _enforce_preflight_budget(source_path, preflight, limits)
    safe_stem = validate_title_decision(title_decision, candidate)

    root = (workspace_root or workspace_root_from_script()).resolve()
    if source.source_kind.startswith("remote"):
        parent = (output_root or (root / "output/convert-researchpaper-to-md")).resolve()
        if not _is_relative_to(parent, root):
            raise SkillError("UNSAFE_PATH", "Remote output_root must stay inside the workspace.", output_root=str(parent))
        # A remote copy already exists in workspace-owned incoming storage. Its
        # title rename must happen before creating the final output parent.
        incoming_target = _choose_rename_target(source_path, source_path.parent, safe_stem, source.sha256)
        titled_incoming, renamed = _rename_source(source_path, incoming_target, source.sha256)
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            raise SkillError(
                "OUTPUT_PARENT_CREATE_FAILED",
                "Remote output parent could not be created after the successful title rename.",
                renamed_pdf=str(titled_incoming),
                output_parent=str(parent),
                reason=str(exc),
            )
        target = _choose_rename_target(titled_incoming, parent, titled_incoming.stem, source.sha256)
        try:
            os.replace(str(titled_incoming), str(target))
        except Exception as exc:
            raise SkillError(
                "REMOTE_PERSIST_FAILED",
                "The title-renamed remote PDF could not be persisted beside its output folder.",
                source=str(titled_incoming),
                target=str(target),
                reason=str(exc),
            )
        if sha256_file(target) != source.sha256:
            raise SkillError("SOURCE_HASH_MISMATCH", "Persisted remote PDF hash changed after its move.", path=str(target))
        renamed_path = target
    else:
        parent = source_path.parent
        target = _choose_rename_target(source_path, parent, safe_stem, source.sha256)
        # Required ordering: this rename is the first final-output mutation.
        renamed_path, renamed = _rename_source(source_path, target, source.sha256)
    output_dir = renamed_path.with_suffix("")
    try:
        output_dir.mkdir(parents=False, exist_ok=True)
    except Exception as exc:
        raise SkillError(
            "OUTPUT_FOLDER_CREATE_FAILED",
            "The title folder could not be created after the successful PDF rename.",
            renamed_pdf=str(renamed_path),
            output_dir=str(output_dir),
            reason=str(exc),
        )

    if not force and _manifest_is_valid(output_dir, source.sha256):
        return {
            "status": "skipped",
            "reason": "valid_manifest",
            "renamed_pdf": str(renamed_path),
            "output_dir": str(output_dir),
            "source_sha256": source.sha256,
        }

    run_id = uuid.uuid4().hex
    staging_dir = output_dir / ".staging" / run_id
    staging_dir.mkdir(parents=True, exist_ok=False)
    try:
        conversion = (docling_engine or DoclingAdapter()).convert(renamed_path, staging_dir)
        if conversion.page_count > limits.max_page_count:
            raise SkillError(
                "RESOURCE_REVIEW_REQUIRED",
                "The converted paper exceeds the configured page-count budget.",
                page_count=conversion.page_count,
                max_page_count=limits.max_page_count,
            )
        original_path = staging_dir / "original.md"
        asset_dir = staging_dir / "Asset"
        if not original_path.is_file() or not original_path.read_text(encoding="utf-8").strip():
            raise SkillError("CONTENT_INCOMPLETE", "Docling did not create a non-empty original Markdown draft.")
        if not asset_dir.is_dir():
            raise SkillError("ASSET_PARITY_FAILED", "Docling did not create the required Asset folder.")
        staging_bytes = _directory_size(staging_dir)
        if staging_bytes > limits.max_staging_bytes:
            raise SkillError(
                "RESOURCE_REVIEW_REQUIRED",
                "Converted artifacts exceed the configured staging-disk budget.",
                staging_bytes=staging_bytes,
                max_staging_bytes=limits.max_staging_bytes,
            )
        audit_plan = _build_source_audit_plan(staging_dir, conversion, limits)
        state = {
            "schema_version": SCHEMA_VERSION,
            "skill_version": SKILL_VERSION,
            "status": "awaiting_ai",
            "run_id": run_id,
            "url_path": source.request_url_path or source.original_location,
            "source_kind": source.source_kind,
            "source_original_name": source.original_name,
            "source_original_location": source.original_location,
            "source_sha256": source.sha256,
            "renamed_pdf": str(renamed_path),
            "renamed": renamed,
            "validated_title": str(title_decision["title"]),
            "safe_title_stem": renamed_path.stem,
            "output_dir": str(output_dir),
            "staging_dir": str(staging_dir),
            "original_draft": str(original_path),
            "lossless_inventory": str(staging_dir / "lossless-docling.json"),
            "asset_dir": str(asset_dir),
            "conversion": asdict(conversion),
            "resource_budget": asdict(limits),
            "source_audit_plan": audit_plan,
            "language_ai_request": {
                "task": "Classify the source language from original.md.",
                "response_schema": {"language": "ISO 639-1 string", "confidence": "number 0..1", "reason": "string"},
            },
            "audit_ai_request": {
                "task": "Audit every source-audit chunk, then synthesize complete coverage without embedding the full paper in one context.",
                "plan_path": audit_plan["path"],
                "plan_sha256": audit_plan["sha256"],
                "chunk_ids": audit_plan["chunk_ids"],
                "response_schema": {
                    "passed": "boolean",
                    "issues": "array of strings",
                    "chunk_ids": "all ordered source-audit chunk IDs",
                    "coverage_complete": "boolean",
                },
            },
        }
        state_path = staging_dir / "job-state.json"
        atomic_write_json(state_path, state)
        state["job_state_path"] = str(state_path)
        return state
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise


def prepare_paper(
    preflight: Mapping[str, Any],
    title_decision: Mapping[str, Any],
    *,
    output_root: Optional[Path] = None,
    force: bool = False,
    docling_engine: Optional[Any] = None,
    workspace_root: Optional[Path] = None,
    budget: Optional[ResourceBudget] = None,
) -> Dict[str, Any]:
    root = (workspace_root or workspace_root_from_script()).resolve()
    source_data = preflight.get("source")
    source_path = Path(str(source_data.get("local_path"))).resolve() if isinstance(source_data, dict) and source_data.get("local_path") else None
    preflight_dir = Path(str(preflight.get("job_dir"))).resolve() if preflight.get("job_dir") else None
    incoming_dir = source_path.parent if source_path is not None and source_data and str(source_data.get("source_kind", "")).startswith("remote") else None
    try:
        result = _prepare_paper_impl(
            preflight,
            title_decision,
            output_root=output_root,
            force=force,
            docling_engine=docling_engine,
            workspace_root=root,
            budget=budget,
        )
    except SkillError as exc:
        cleanup = _cleanup_converter_scratch(root, preflight_dir, incoming_dir)
        exc.details.setdefault("scratch_cleanup", cleanup)
        raise
    cleanup = _cleanup_converter_scratch(root, preflight_dir, incoming_dir)
    result["scratch_cleanup"] = cleanup
    return result


def _validate_language_decision(decision: Mapping[str, Any]) -> Tuple[str, float]:
    language = decision.get("language")
    confidence = decision.get("confidence")
    if not isinstance(language, str) or not isinstance(confidence, (int, float)):
        raise SkillError("INVALID_AI_RESPONSE", "Language decision must include language and confidence.")
    normalized = language.strip().lower().split("-")[0]
    if len(normalized) != 2 or float(confidence) < MIN_TITLE_CONFIDENCE:
        raise SkillError("LANGUAGE_REVIEW_REQUIRED", "Source language is not known with sufficient confidence.", language=language, confidence=confidence)
    return normalized, float(confidence)


def _validate_audit(audit: Mapping[str, Any], state: Mapping[str, Any]) -> None:
    issues = audit.get("issues")
    if audit.get("passed") is not True or not isinstance(issues, list) or issues:
        raise SkillError("AI_AUDIT_FAILED", "Built-in AI audit reported unresolved content or structure issues.", issues=issues)
    plan = state.get("source_audit_plan")
    expected_ids = plan.get("chunk_ids") if isinstance(plan, dict) else None
    if not isinstance(expected_ids, list) or not expected_ids:
        raise SkillError("INVALID_JOB_STATE", "Source-audit plan is missing from the conversion state.")
    if audit.get("coverage_complete") is not True or audit.get("chunk_ids") != expected_ids:
        raise SkillError(
            "AI_AUDIT_FAILED",
            "Built-in AI audit did not prove complete ordered chunk coverage.",
            expected_chunk_ids=expected_ids,
            actual_chunk_ids=audit.get("chunk_ids"),
        )


def _run_source_audit(ai_runner: Any, state: Mapping[str, Any], language_decision: Mapping[str, Any]) -> Mapping[str, Any]:
    """Use chunk-aware adapters when available and require one final synthesis."""

    plan = state.get("source_audit_plan")
    if not isinstance(plan, dict) or not isinstance(plan.get("chunks"), list):
        raise SkillError("INVALID_JOB_STATE", "Source-audit plan is unavailable.")
    chunk_runner = getattr(ai_runner, "audit_source_chunk", None)
    synthesizer = getattr(ai_runner, "synthesize_source_audit", None)
    if callable(chunk_runner) and callable(synthesizer):
        chunk_results = [chunk_runner(state, language_decision, chunk) for chunk in plan["chunks"]]
        return synthesizer(state, language_decision, chunk_results)
    return ai_runner.audit_source(state, language_decision)


def _artifact_hashes(staging_dir: Path) -> Dict[str, str]:
    hashes = {"original.md": sha256_file(staging_dir / "original.md")}
    asset_dir = staging_dir / "Asset"
    for path in sorted(asset_dir.rglob("*")):
        if path.is_file():
            hashes[path.relative_to(staging_dir).as_posix()] = sha256_file(path)
    return hashes


def _transactional_publish(staging_dir: Path, output_dir: Path, manifest: Dict[str, Any]) -> None:
    backup_dir = staging_dir / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target_names = ["original.md", "Asset"]
    moved_old: List[str] = []
    installed: List[str] = []
    try:
        for name in target_names:
            target = output_dir / name
            if target.exists():
                os.replace(str(target), str(backup_dir / name))
                moved_old.append(name)
        for name in ["original.md", "Asset"]:
            os.replace(str(staging_dir / name), str(output_dir / name))
            installed.append(name)
        # Commit marker is intentionally written last.
        atomic_write_json(output_dir / ".conversion-manifest.json", manifest)
    except Exception as exc:
        for name in reversed(installed):
            target = output_dir / name
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink()
        for name in reversed(moved_old):
            backup = backup_dir / name
            if backup.exists():
                os.replace(str(backup), str(output_dir / name))
        raise SkillError("PUBLICATION_FAILED", "Final artifacts could not be published transactionally.", output_dir=str(output_dir), reason=str(exc))


def _publish_paper_impl(
    state: Mapping[str, Any],
    language_decision: Mapping[str, Any],
    audit_decision: Mapping[str, Any],
) -> Dict[str, Any]:
    if state.get("status") != "awaiting_ai":
        raise SkillError("INVALID_JOB_STATE", "Job state is not ready for publication.")
    staging_dir = Path(str(state.get("staging_dir"))).resolve()
    output_dir = Path(str(state.get("output_dir"))).resolve()
    if not _is_relative_to(staging_dir, output_dir / ".staging"):
        raise SkillError("UNSAFE_PATH", "Job staging directory is outside its owned output staging root.")
    original_path = staging_dir / "original.md"
    asset_dir = staging_dir / "Asset"
    if not original_path.is_file() or not asset_dir.is_dir():
        raise SkillError("INVALID_JOB_STATE", "Prepared Markdown or Asset directory is missing.")
    language, confidence = _validate_language_decision(language_decision)
    _validate_audit(audit_decision, state)
    hashes = _artifact_hashes(staging_dir)
    manifest_path = output_dir / ".conversion-manifest.json"
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "skill_version": SKILL_VERSION,
        "status": "success",
        "url_path": state.get("url_path") or state.get("source_original_location"),
        "source_identity": {
            "source_type": state.get("source_kind"),
            "requested_url": state.get("url_path") or state.get("source_original_location"),
            "resolved_url": state.get("source_original_location"),
            "original_name": state.get("source_original_name"),
        },
        "source_sha256": state.get("source_sha256"),
        "renamed_pdf": state.get("renamed_pdf"),
        "paper_folder": str(output_dir),
        "original_md": str(output_dir / "original.md"),
        "original_md_sha256": hashes["original.md"],
        "asset_dir": str(output_dir / "Asset"),
        "manifest": str(manifest_path),
        "validated_title": state.get("validated_title"),
        "source_language": {"language": language, "confidence": confidence},
        "docling_version": (state.get("conversion") or {}).get("docling_version"),
        "conversion_status": (state.get("conversion") or {}).get("conversion_status"),
        "asset_inventory": (state.get("conversion") or {}).get("asset_inventory", []),
        "artifact_hashes": hashes,
        "source_audit": dict(audit_decision),
    }
    _transactional_publish(staging_dir, output_dir, manifest)
    shutil.rmtree(staging_dir, ignore_errors=True)
    staging_parent = output_dir / ".staging"
    try:
        staging_parent.rmdir()
    except OSError:
        pass
    return {
        "status": "success",
        "renamed_pdf": state.get("renamed_pdf"),
        "output_dir": str(output_dir),
        "original_md": str(output_dir / "original.md"),
        "asset_dir": str(output_dir / "Asset"),
        "manifest": str(manifest_path),
        "source_language": {"language": language, "confidence": confidence},
        "handoff_schema_version": MANIFEST_SCHEMA_VERSION,
    }


def publish_paper(
    state: Mapping[str, Any],
    language_decision: Mapping[str, Any],
    audit_decision: Mapping[str, Any],
) -> Dict[str, Any]:
    try:
        return _publish_paper_impl(state, language_decision, audit_decision)
    except SkillError as exc:
        staging_value = state.get("staging_dir")
        output_value = state.get("output_dir")
        cleanup = {"removed": [], "retained": []}
        if isinstance(staging_value, str) and staging_value and isinstance(output_value, str) and output_value:
            staging = Path(staging_value).resolve()
            owned_root = Path(output_value).resolve() / ".staging"
            if staging != owned_root and _is_relative_to(staging, owned_root):
                try:
                    shutil.rmtree(staging)
                    cleanup["removed"].append(str(staging))
                    try:
                        owned_root.rmdir()
                    except OSError:
                        pass
                except OSError:
                    cleanup["retained"].append(str(staging))
        exc.details.setdefault("staging_cleanup", cleanup)
        raise


def inspect_handoff(
    url_path: str,
    prior_handoff: Union[Mapping[str, Any], Path, str],
    *,
    workspace_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Validate a prior converter result before discovery, preflight, or AI."""

    root = (workspace_root or workspace_root_from_script()).resolve()
    if isinstance(prior_handoff, Mapping):
        handoff = dict(prior_handoff)
        handoff_path = None
    else:
        handoff_path = Path(prior_handoff).resolve()
        if not _is_relative_to(handoff_path, root) or not handoff_path.is_file():
            raise SkillError("HANDOFF_NOT_FOUND", "Prior converter handoff is unavailable inside the workspace.", path=str(handoff_path))
        handoff = read_json(handoff_path)
    if handoff.get("schema_version") == MANIFEST_SCHEMA_VERSION:
        manifest = handoff
        manifest_path = handoff_path or Path(str(manifest.get("manifest", ""))).resolve()
    else:
        results = handoff.get("results")
        candidates = [item for item in results or [] if isinstance(item, dict) and item.get("status") in {"success", "skipped"}]
        if len(candidates) != 1:
            raise SkillError("HANDOFF_NOT_FOUND", "Prior handoff must contain exactly one successful paper.", count=len(candidates))
        manifest_path = Path(str(candidates[0].get("manifest", ""))).resolve()
        if not _is_relative_to(manifest_path, root) or not manifest_path.is_file():
            raise SkillError("HANDOFF_NOT_FOUND", "Prior manifest is unavailable inside the workspace.", path=str(manifest_path))
        manifest = read_json(manifest_path)
    if not _is_relative_to(manifest_path, root) or manifest_path.name != ".conversion-manifest.json":
        raise SkillError("HANDOFF_SCHEMA_INVALID", "Prior manifest path is invalid.", path=str(manifest_path))
    if manifest.get("url_path") != url_path:
        raise SkillError(
            "SOURCE_IDENTITY_MISMATCH",
            "Prior manifest belongs to a different url_path.",
            requested=url_path,
            recorded=manifest.get("url_path"),
        )
    output_dir = Path(str(manifest.get("paper_folder", ""))).resolve()
    renamed_pdf = Path(str(manifest.get("renamed_pdf", ""))).resolve()
    if not _is_relative_to(output_dir, root) or manifest_path != output_dir / ".conversion-manifest.json":
        raise SkillError("HANDOFF_SCHEMA_INVALID", "Prior paper-folder or manifest path is invalid.")
    if renamed_pdf != output_dir.with_suffix(".pdf") or not renamed_pdf.is_file():
        raise SkillError("HANDOFF_NOT_FOUND", "Prior renamed PDF is missing or misplaced.", path=str(renamed_pdf))
    source_hash = str(manifest.get("source_sha256") or "")
    if validate_pdf(renamed_pdf) != source_hash or not _manifest_is_valid(output_dir, source_hash):
        raise SkillError("SOURCE_HASH_MISMATCH", "Prior converter artifacts no longer match their manifest.")
    return {
        "status": "valid",
        "reason": "valid_prior_handoff",
        "url_path": url_path,
        "renamed_pdf": str(renamed_pdf),
        "output_dir": str(output_dir),
        "original_md": str(output_dir / "original.md"),
        "asset_dir": str(output_dir / "Asset"),
        "manifest": str(manifest_path),
        "source_language": manifest.get("source_language"),
        "source_sha256": source_hash,
    }


def convert_research_papers(
    url_path: str,
    *,
    force: bool = False,
    output_root: Optional[Path] = None,
    ai_runner: Optional[Any] = None,
    http_client: Optional[Any] = None,
    docling_engine: Optional[Any] = None,
    workspace_root: Optional[Path] = None,
    prior_handoff: Optional[Union[Mapping[str, Any], Path, str]] = None,
    budget: Optional[ResourceBudget] = None,
) -> Dict[str, Any]:
    """Run source-only conversion with an injected host-AI adapter.

    ai_runner must implement validate_title(preflight), detect_language(state),
    and audit_source(state, language_decision).
    """
    root = (workspace_root or workspace_root_from_script()).resolve()
    limits = (budget or ResourceBudget()).validate()
    if prior_handoff is not None and not force:
        inspected = inspect_handoff(url_path, prior_handoff, workspace_root=root)
        skipped = {**inspected, "status": "skipped"}
        return {
            "status": "success",
            "url_path": url_path,
            "source_type": "prior_handoff",
            "pdf_count": 1,
            "succeeded": 1,
            "failed": 0,
            "results": [skipped],
        }
    if ai_runner is None:
        raise SkillError(
            "AI_RUNNER_REQUIRED",
            "The host built-in AI must be supplied, or the CLI phases must be orchestrated by the agent.",
        )
    discovery = discover_sources(url_path, workspace_root=root, http_client=http_client, budget=limits)
    if len(discovery["sources"]) != 1:
        cleanup = _cleanup_converter_scratch(
            root,
            *(Path(item["local_path"]).resolve().parent for item in discovery["sources"] if str(item.get("source_kind", "")).startswith("remote")),
        )
        return {
            "status": "error",
            "error_code": "MULTIPLE_PDFS_DISCOVERED",
            "message": "Exactly one research paper must be selected per workflow run.",
            "url_path": url_path,
            "source_type": discovery["source_type"],
            "pdf_count": len(discovery["sources"]),
            "succeeded": 0,
            "failed": len(discovery["sources"]),
            "results": [],
            "details": {"scratch_cleanup": cleanup},
        }
    results: List[Dict[str, Any]] = []
    for source_data in discovery["sources"]:
        source = SourceRecord(**source_data)
        preflight: Optional[Dict[str, Any]] = None
        try:
            preflight = run_preflight(source, docling_engine=docling_engine, workspace_root=root)
            title_decision = ai_runner.validate_title(preflight)
            state = prepare_paper(
                preflight,
                title_decision,
                output_root=output_root,
                force=force,
                docling_engine=docling_engine,
                workspace_root=root,
                budget=limits,
            )
            if state.get("status") == "skipped":
                results.append(state)
                continue
            language_decision = ai_runner.detect_language(state)
            _validate_language_decision(language_decision)
            audit_decision = _run_source_audit(ai_runner, state, language_decision)
            results.append(publish_paper(state, language_decision, audit_decision))
        except SkillError as exc:
            cleanup = _cleanup_converter_scratch(
                root,
                Path(str(preflight.get("job_dir"))).resolve() if preflight and preflight.get("job_dir") else None,
                Path(source.local_path).resolve().parent if source.source_kind.startswith("remote") else None,
            )
            exc.details.setdefault("scratch_cleanup", cleanup)
            failure = exc.to_dict()
            failure["source"] = asdict(source)
            results.append(failure)
        except Exception as exc:
            cleanup = _cleanup_converter_scratch(
                root,
                Path(str(preflight.get("job_dir"))).resolve() if preflight and preflight.get("job_dir") else None,
                Path(source.local_path).resolve().parent if source.source_kind.startswith("remote") else None,
            )
            results.append(
                {
                    "status": "error",
                    "error_code": "UNEXPECTED_ERROR",
                    "message": str(exc),
                    "source": asdict(source),
                    "details": {"scratch_cleanup": cleanup},
                }
            )
    succeeded = sum(item.get("status") in {"success", "skipped"} for item in results)
    review = sum(item.get("status") == "review_required" or str(item.get("error_code", "")).endswith("REVIEW_REQUIRED") for item in results)
    if succeeded == len(results):
        status = "success"
    elif succeeded:
        status = "partial_success"
    elif review:
        status = "review_required"
    else:
        status = "error"
    return {
        "status": status,
        "url_path": url_path,
        "source_type": discovery["source_type"],
        "pdf_count": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }


def inspect_output(output_dir: Path) -> Dict[str, Any]:
    output = output_dir.resolve()
    manifest = _load_manifest(output)
    if not manifest:
        return {"status": "invalid", "reason": "manifest_missing_or_invalid", "output_dir": str(output)}
    valid = _manifest_is_valid(output, str(manifest.get("source_sha256", "")))
    return {"status": "valid" if valid else "invalid", "output_dir": str(output), "manifest": manifest}


def _source_from_cli(path: str, source_kind: str, original_location: Optional[str]) -> SourceRecord:
    source_path = Path(path).resolve()
    requested = original_location or str(source_path)
    return SourceRecord(requested, str(source_path), source_kind, validate_pdf(source_path), source_path.name, requested)


def _add_budget_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-pdf-bytes", type=int, default=MAX_PDF_BYTES)
    parser.add_argument("--max-page-count", type=int, default=DEFAULT_MAX_PAGE_COUNT)
    parser.add_argument("--max-staging-bytes", type=int, default=DEFAULT_MAX_STAGING_BYTES)
    parser.add_argument("--audit-items-per-chunk", type=int, default=DEFAULT_AUDIT_ITEMS_PER_CHUNK)
    parser.add_argument("--audit-chars-per-chunk", type=int, default=DEFAULT_AUDIT_CHARS_PER_CHUNK)
    parser.add_argument("--max-audit-chunks", type=int, default=DEFAULT_MAX_AUDIT_CHUNKS)


def _budget_from_args(args: argparse.Namespace) -> ResourceBudget:
    return ResourceBudget(
        max_pdf_bytes=args.max_pdf_bytes,
        max_page_count=args.max_page_count,
        max_staging_bytes=args.max_staging_bytes,
        audit_items_per_chunk=args.audit_items_per_chunk,
        audit_chars_per_chunk=args.audit_chars_per_chunk,
        max_audit_chunks=args.max_audit_chunks,
    ).validate()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check-dependencies")

    discover = subparsers.add_parser("discover")
    discover.add_argument("--url-path", required=True)
    discover.add_argument("--workspace-root", type=Path)
    _add_budget_arguments(discover)

    inspect_handoff_parser = subparsers.add_parser("inspect-handoff")
    inspect_handoff_parser.add_argument("--url-path", required=True)
    inspect_handoff_parser.add_argument("--handoff-json", type=Path, required=True)
    inspect_handoff_parser.add_argument("--workspace-root", type=Path)

    preflight = subparsers.add_parser("preflight-title")
    preflight.add_argument("--source", required=True)
    preflight.add_argument("--source-kind", default="local_pdf")
    preflight.add_argument("--original-location")
    preflight.add_argument("--workspace-root", type=Path)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--preflight-json", type=Path, required=True)
    prepare.add_argument("--title-decision-json", type=Path, required=True)
    prepare.add_argument("--output-root", type=Path)
    prepare.add_argument("--workspace-root", type=Path)
    prepare.add_argument("--force", action="store_true")
    _add_budget_arguments(prepare)

    publish = subparsers.add_parser("publish")
    publish.add_argument("--job-state", type=Path, required=True)
    publish.add_argument("--language-decision-json", type=Path, required=True)
    publish.add_argument("--audit-json", type=Path, required=True)

    inspect = subparsers.add_parser("inspect-output")
    inspect.add_argument("--output-dir", type=Path, required=True)
    return parser


def _print_docling_progress(event: Dict[str, Any]) -> None:
    print(json.dumps({"type": "docling_progress", **event}, ensure_ascii=False), file=sys.stderr, flush=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "check-dependencies":
            result = DoclingAdapter.dependency_report()
        elif args.command == "discover":
            result = discover_sources(args.url_path, workspace_root=args.workspace_root, budget=_budget_from_args(args))
        elif args.command == "inspect-handoff":
            result = inspect_handoff(args.url_path, args.handoff_json, workspace_root=args.workspace_root)
        elif args.command == "preflight-title":
            source = _source_from_cli(args.source, args.source_kind, args.original_location)
            result = run_preflight(
                source,
                docling_engine=DoclingAdapter(progress_callback=_print_docling_progress),
                workspace_root=args.workspace_root,
                budget=_budget_from_args(args),
            )
        elif args.command == "prepare":
            result = prepare_paper(
                read_json(args.preflight_json),
                read_json(args.title_decision_json),
                output_root=args.output_root,
                force=args.force,
                docling_engine=DoclingAdapter(progress_callback=_print_docling_progress),
                workspace_root=args.workspace_root,
            )
        elif args.command == "publish":
            result = publish_paper(
                read_json(args.job_state),
                read_json(args.language_decision_json),
                read_json(args.audit_json),
            )
        elif args.command == "inspect-output":
            result = inspect_output(args.output_dir)
        else:
            raise SkillError("INVALID_COMMAND", "Unsupported command.")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("available", True) and result.get("status") not in {"error", "invalid"} else 2
    except SkillError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
