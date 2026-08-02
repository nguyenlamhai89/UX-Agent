#!/usr/bin/env python3
"""Deterministic PDF-to-Markdown pipeline for the Codex skill.

Docling owns PDF extraction and document structure. The host agent's built-in
AI owns title confirmation, language classification, translation, and semantic
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
import unicodedata
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SKILL_VERSION = "1.0.0"
SCHEMA_VERSION = 1
MAX_PDF_BYTES = 100 * 1024 * 1024
MAX_COLLECTION_BYTES = 5 * 1024 * 1024
MAX_REMOTE_PDFS = 50
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


@dataclass
class PreflightBundle:
    candidates: List[Dict[str, Any]]
    selected_candidate: Optional[Dict[str, Any]]
    first_page_image: Optional[str]
    docling_version: str
    conversion_status: str


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
    """Small bounded HTTP reader used only for public PDF discovery/download."""

    def fetch(self, url: str, max_bytes: int) -> Tuple[str, str, bytes]:
        _reject_unsafe_remote_host(url)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "convert-researchpaper-to-md/%s" % SKILL_VERSION},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                final_url = response.geturl()
                _reject_unsafe_remote_host(final_url)
                length = response.headers.get("Content-Length")
                if length and int(length) > max_bytes:
                    raise SkillError(
                        "REMOTE_TOO_LARGE",
                        "Remote response exceeds the configured size limit.",
                        url=url,
                        max_bytes=max_bytes,
                    )
                data = response.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise SkillError(
                        "REMOTE_TOO_LARGE",
                        "Remote response exceeds the configured size limit.",
                        url=url,
                        max_bytes=max_bytes,
                    )
                return final_url, response.headers.get_content_type(), data
        except SkillError:
            raise
        except Exception as exc:
            raise SkillError("REMOTE_FETCH_FAILED", "Unable to fetch remote input.", url=url, reason=str(exc))


def workspace_root_from_script() -> Path:
    return Path(__file__).resolve().parents[4]


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
        raise SkillError("REMOTE_FETCH_FAILED", "Remote hostname could not be resolved.", url=url, reason=str(exc))
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


def _persist_remote_pdf(url: str, data: bytes, incoming_root: Path) -> SourceRecord:
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
    return SourceRecord(url, str(target), "remote_pdf", digest, target.name)


def discover_sources(
    url_path: str,
    *,
    workspace_root: Optional[Path] = None,
    http_client: Optional[Any] = None,
) -> Dict[str, Any]:
    if not isinstance(url_path, str) or not url_path.strip():
        raise SkillError("INVALID_INPUT", "url_path must be a non-empty string.")
    root = (workspace_root or workspace_root_from_script()).resolve()
    parsed = urllib.parse.urlparse(url_path)

    if parsed.scheme in {"", "file"}:
        raw_path = urllib.request.url2pathname(parsed.path) if parsed.scheme == "file" else url_path
        paths = _local_pdf_paths(Path(raw_path), root)
        records = [
            SourceRecord(url_path, str(path.resolve()), "file_pdf" if parsed.scheme == "file" else "local_pdf", validate_pdf(path), path.name)
            for path in paths
        ]
        source_type = "file_directory" if parsed.scheme == "file" and len(paths) > 1 else "local_directory" if len(paths) > 1 else records[0].source_kind
    elif parsed.scheme in {"http", "https"}:
        client = http_client or UrllibHttpClient()
        final_url, content_type, data = client.fetch(url_path, MAX_PDF_BYTES)
        incoming_root = root / ".agents/scratch/convert-researchpaper-to-md/incoming"
        if data.startswith(b"%PDF-") or content_type == "application/pdf":
            records = [_persist_remote_pdf(final_url, data, incoming_root)]
            source_type = "remote_pdf"
        else:
            if len(data) > MAX_COLLECTION_BYTES:
                raise SkillError("REMOTE_TOO_LARGE", "Remote collection page is too large.", url=url_path)
            parser = _PdfLinkParser()
            parser.feed(data.decode("utf-8", errors="replace"))
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
                resolved_url, _mime, pdf_data = client.fetch(link, MAX_PDF_BYTES)
                record = _persist_remote_pdf(resolved_url, pdf_data, incoming_root)
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
        self._emit("docling_preflight_complete", 20, status=status, candidate_count=len(candidates))
        return PreflightBundle(candidates, selected, str(image_path) if image_path else None, api["version"], status)

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
        "title_ai_request": {
            "task": "Confirm the first true research-paper title using the candidate and first-page render.",
            "response_schema": {"valid": "boolean", "confidence": "number 0..1", "title": "string", "reason": "string"},
        },
    }
    preflight_path = job_dir / "preflight.json"
    atomic_write_json(preflight_path, payload)
    payload["preflight_path"] = str(preflight_path)
    return payload


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
    if not manifest or manifest.get("source_sha256") != source_hash or manifest.get("status") != "success":
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


def prepare_paper(
    preflight: Mapping[str, Any],
    title_decision: Mapping[str, Any],
    *,
    output_root: Optional[Path] = None,
    force: bool = False,
    docling_engine: Optional[Any] = None,
    workspace_root: Optional[Path] = None,
) -> Dict[str, Any]:
    source_data = preflight.get("source")
    candidate = preflight.get("selected_candidate")
    if not isinstance(source_data, dict) or not isinstance(candidate, dict):
        raise SkillError("INVALID_PREFLIGHT", "Preflight data is missing its source or title candidate.")
    source = SourceRecord(**source_data)
    source_path = Path(source.local_path).resolve()
    if validate_pdf(source_path) != source.sha256:
        raise SkillError("SOURCE_CHANGED", "PDF changed after title preflight; restart the conversion.", path=str(source_path))
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
        original_path = staging_dir / "original.md"
        asset_dir = staging_dir / "Asset"
        if not original_path.is_file() or not original_path.read_text(encoding="utf-8").strip():
            raise SkillError("CONTENT_INCOMPLETE", "Docling did not create a non-empty original Markdown draft.")
        if not asset_dir.is_dir():
            raise SkillError("ASSET_PARITY_FAILED", "Docling did not create the required Asset folder.")
        state = {
            "schema_version": SCHEMA_VERSION,
            "skill_version": SKILL_VERSION,
            "status": "awaiting_ai",
            "run_id": run_id,
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
            "language_ai_request": {
                "task": "Classify the source language from original.md.",
                "response_schema": {"language": "ISO 639-1 string", "confidence": "number 0..1", "reason": "string"},
            },
            "translation_ai_request": {
                "task": "If non-Vietnamese, translate all natural-language content to Vietnamese without changing Markdown structure or protected tokens.",
                "output": "UTF-8 Markdown file",
            },
            "audit_ai_request": {
                "task": "Audit original.md and vie.md for omissions, additions, or structural changes.",
                "response_schema": {"passed": "boolean", "issues": "array of strings"},
            },
        }
        state_path = staging_dir / "job-state.json"
        atomic_write_json(state_path, state)
        state["job_state_path"] = str(state_path)
        return state
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise


def _table_shape(lines: Sequence[str], start: int) -> Tuple[int, int, int]:
    index = start
    rows: List[str] = []
    while index < len(lines) and lines[index].strip().startswith("|") and lines[index].strip().endswith("|"):
        rows.append(lines[index].strip())
        index += 1
    columns = max((max(0, row.count("|") - 1) for row in rows), default=0)
    return len(rows), columns, index


def markdown_structure_signature(markdown: str) -> Dict[str, Any]:
    lines = markdown.splitlines()
    heading_levels: List[int] = []
    tables: List[List[int]] = []
    block_sequence: List[str] = []
    in_fence = False
    fence_count = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.match(r"^\s*```", line):
            in_fence = not in_fence
            fence_count += 1
            block_sequence.append("CODE_FENCE")
            index += 1
            continue
        if not in_fence:
            heading = re.match(r"^(#{1,6})\s+\S", line)
            if heading:
                level = len(heading.group(1))
                heading_levels.append(level)
                block_sequence.append("H%d" % level)
            if line.strip().startswith("|") and line.strip().endswith("|"):
                rows, columns, next_index = _table_shape(lines, index)
                if rows >= 2:
                    tables.append([rows, columns])
                    block_sequence.append("TABLE:%dx%d" % (rows, columns))
                    index = next_index
                    continue
            for _match in re.finditer(r"!\[[^\]]*\]\(([^)]+)\)", line):
                block_sequence.append("IMAGE")
        index += 1
    image_targets = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown)
    urls = re.findall(r"https?://[^\s)>\]]+", markdown)
    dois = re.findall(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", markdown, flags=re.IGNORECASE)
    numbers = re.findall(r"(?<![\w])[-+]?\d+(?:[.,]\d+)*(?:%|°[CF])?", markdown)
    citations = re.findall(r"\[(?:\d+[;,\-\s]*)+\]", markdown)
    formula_markers = len(re.findall(r"\$\$|(?<!\\)\$", markdown))
    return {
        "heading_levels": heading_levels,
        "tables": tables,
        "image_targets": image_targets,
        "block_sequence": block_sequence,
        "fence_count": fence_count,
        "formula_markers": formula_markers,
        "urls": sorted(Counter(urls).items()),
        "dois": sorted(Counter(item.lower() for item in dois).items()),
        "numbers": sorted(Counter(numbers).items()),
        "citations": sorted(Counter(citations).items()),
    }


def validate_markdown_parity(original: str, vietnamese: str) -> Dict[str, Any]:
    original_signature = markdown_structure_signature(original)
    vietnamese_signature = markdown_structure_signature(vietnamese)
    mismatches = []
    for field in (
        "heading_levels",
        "tables",
        "image_targets",
        "block_sequence",
        "fence_count",
        "formula_markers",
        "urls",
        "dois",
        "numbers",
        "citations",
    ):
        if original_signature[field] != vietnamese_signature[field]:
            mismatches.append(field)
    if mismatches:
        raise SkillError("STRUCTURE_PARITY_FAILED", "Vietnamese Markdown changed protected structure or information tokens.", mismatches=mismatches)
    return {"original": original_signature, "vietnamese": vietnamese_signature}


def _validate_language_decision(decision: Mapping[str, Any]) -> Tuple[str, float]:
    language = decision.get("language")
    confidence = decision.get("confidence")
    if not isinstance(language, str) or not isinstance(confidence, (int, float)):
        raise SkillError("INVALID_AI_RESPONSE", "Language decision must include language and confidence.")
    normalized = language.strip().lower().split("-")[0]
    if len(normalized) != 2 or float(confidence) < MIN_TITLE_CONFIDENCE:
        raise SkillError("LANGUAGE_REVIEW_REQUIRED", "Source language is not known with sufficient confidence.", language=language, confidence=confidence)
    return normalized, float(confidence)


def _validate_audit(audit: Mapping[str, Any]) -> None:
    issues = audit.get("issues")
    if audit.get("passed") is not True or not isinstance(issues, list) or issues:
        raise SkillError("AI_AUDIT_FAILED", "Built-in AI audit reported unresolved content or structure issues.", issues=issues)


def _artifact_hashes(staging_dir: Path, include_vie: bool) -> Dict[str, str]:
    hashes = {"original.md": sha256_file(staging_dir / "original.md")}
    if include_vie:
        hashes["vie.md"] = sha256_file(staging_dir / "vie.md")
    asset_dir = staging_dir / "Asset"
    for path in sorted(asset_dir.rglob("*")):
        if path.is_file():
            hashes[path.relative_to(staging_dir).as_posix()] = sha256_file(path)
    return hashes


def _transactional_publish(staging_dir: Path, output_dir: Path, manifest: Dict[str, Any], include_vie: bool) -> None:
    backup_dir = staging_dir / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target_names = ["original.md", "Asset", "vie.md"]
    moved_old: List[str] = []
    installed: List[str] = []
    try:
        for name in target_names:
            target = output_dir / name
            if target.exists():
                os.replace(str(target), str(backup_dir / name))
                moved_old.append(name)
        for name in ["original.md", "Asset"] + (["vie.md"] if include_vie else []):
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


def publish_paper(
    state: Mapping[str, Any],
    language_decision: Mapping[str, Any],
    audit_decision: Mapping[str, Any],
    *,
    vietnamese_markdown: Optional[Path] = None,
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
    original = original_path.read_text(encoding="utf-8")
    language, confidence = _validate_language_decision(language_decision)
    include_vie = language != "vi"
    signatures: Dict[str, Any]
    if include_vie:
        if vietnamese_markdown is None or not vietnamese_markdown.is_file():
            raise SkillError("TRANSLATION_REQUIRED", "A Vietnamese Markdown translation is required for a non-Vietnamese paper.")
        translated = vietnamese_markdown.read_text(encoding="utf-8")
        if not translated.strip():
            raise SkillError("TRANSLATION_INCOMPLETE", "Vietnamese Markdown translation is empty.")
        signatures = validate_markdown_parity(original, translated)
        atomic_write_text(staging_dir / "vie.md", translated.rstrip() + "\n")
    else:
        signatures = {"original": markdown_structure_signature(original), "vietnamese": None}
        stale = staging_dir / "vie.md"
        if stale.exists():
            stale.unlink()
    _validate_audit(audit_decision)
    hashes = _artifact_hashes(staging_dir, include_vie)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "skill_version": SKILL_VERSION,
        "status": "success",
        "source_original_name": state.get("source_original_name"),
        "source_original_location": state.get("source_original_location"),
        "source_sha256": state.get("source_sha256"),
        "renamed_pdf": state.get("renamed_pdf"),
        "validated_title": state.get("validated_title"),
        "source_language": language,
        "language_confidence": confidence,
        "vietnamese_created": include_vie,
        "docling_version": (state.get("conversion") or {}).get("docling_version"),
        "conversion_status": (state.get("conversion") or {}).get("conversion_status"),
        "asset_inventory": (state.get("conversion") or {}).get("asset_inventory", []),
        "structural_signatures": signatures,
        "artifact_hashes": hashes,
        "ai_audit": dict(audit_decision),
    }
    _transactional_publish(staging_dir, output_dir, manifest, include_vie)
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
        "vie_md": str(output_dir / "vie.md") if include_vie else None,
        "asset_dir": str(output_dir / "Asset"),
        "manifest": str(output_dir / ".conversion-manifest.json"),
        "source_language": language,
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
) -> Dict[str, Any]:
    """Run the complete batch with an injected host-AI adapter.

    ai_runner must implement validate_title(preflight), detect_language(state),
    translate(state), and audit(state, language_decision, translation_path).
    """
    if ai_runner is None:
        raise SkillError(
            "AI_RUNNER_REQUIRED",
            "The host built-in AI must be supplied, or the CLI phases must be orchestrated by the agent.",
        )
    discovery = discover_sources(url_path, workspace_root=workspace_root, http_client=http_client)
    results: List[Dict[str, Any]] = []
    for source_data in discovery["sources"]:
        source = SourceRecord(**source_data)
        try:
            preflight = run_preflight(source, docling_engine=docling_engine, workspace_root=workspace_root)
            title_decision = ai_runner.validate_title(preflight)
            state = prepare_paper(
                preflight,
                title_decision,
                output_root=output_root,
                force=force,
                docling_engine=docling_engine,
                workspace_root=workspace_root,
            )
            if state.get("status") == "skipped":
                results.append(state)
                continue
            language_decision = ai_runner.detect_language(state)
            language, _confidence = _validate_language_decision(language_decision)
            translation_path = None if language == "vi" else ai_runner.translate(state)
            audit_decision = ai_runner.audit(state, language_decision, translation_path)
            results.append(publish_paper(state, language_decision, audit_decision, vietnamese_markdown=translation_path))
        except SkillError as exc:
            failure = exc.to_dict()
            failure["source"] = asdict(source)
            results.append(failure)
        except Exception as exc:
            results.append(
                {
                    "status": "error",
                    "error_code": "UNEXPECTED_ERROR",
                    "message": str(exc),
                    "source": asdict(source),
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
    return SourceRecord(original_location or str(source_path), str(source_path), source_kind, validate_pdf(source_path), source_path.name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check-dependencies")

    discover = subparsers.add_parser("discover")
    discover.add_argument("--url-path", required=True)
    discover.add_argument("--workspace-root", type=Path)

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

    publish = subparsers.add_parser("publish")
    publish.add_argument("--job-state", type=Path, required=True)
    publish.add_argument("--language-decision-json", type=Path, required=True)
    publish.add_argument("--audit-json", type=Path, required=True)
    publish.add_argument("--vie-markdown", type=Path)

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
            result = discover_sources(args.url_path, workspace_root=args.workspace_root)
        elif args.command == "preflight-title":
            source = _source_from_cli(args.source, args.source_kind, args.original_location)
            result = run_preflight(
                source,
                docling_engine=DoclingAdapter(progress_callback=_print_docling_progress),
                workspace_root=args.workspace_root,
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
                vietnamese_markdown=args.vie_markdown,
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
