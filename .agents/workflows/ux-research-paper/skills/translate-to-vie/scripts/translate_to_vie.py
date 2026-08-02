#!/usr/bin/env python3
"""Deterministic Vietnamese research-paper translation runtime.

The host Built-in AI analyzes voice/tone, translates stable Markdown blocks,
and audits the complete result. This module validates every AI handoff,
reassembles Markdown from the source, and publishes files transactionally. It
never reads `.env` and never imports an external LLM SDK.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union


SKILL_VERSION = "1.1.0"
MANIFEST_SCHEMA_VERSION = "converter-manifest-v2"
APPROVAL_SCHEMA_VERSION = "approval-v1"
VOICE_SCHEMA_VERSION = "voice-tone-v1"
TRANSLATION_SCHEMA_VERSION = "translation-v1"
AUDIT_SCHEMA_VERSION = "translation-audit-v1"
TRANSLATION_CHUNK_PLAN_VERSION = "translation-chunk-plan-v1"
BLOCK_INVENTORY_VERSION = "markdown-block-inventory-v1"
DEFAULT_MAX_SOURCE_CHARS = 2_000_000
DEFAULT_MAX_ESTIMATED_TOKENS = 500_000
DEFAULT_MAX_BLOCKS = 20_000
DEFAULT_MAX_BLOCKS_PER_CHUNK = 80
DEFAULT_MAX_CHARS_PER_CHUNK = 24_000
DEFAULT_MAX_TOKENS_PER_CHUNK = 6_000
DEFAULT_MAX_TRANSLATION_CHUNKS = 200
DEFAULT_MAX_AI_ATTEMPTS = 3
MIN_LANGUAGE_CONFIDENCE = 0.85
AFFIRMATIVE_WORDS = {"approve", "approved", "yes", "ok", "đồng ý", "duyệt"}


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


@dataclass(frozen=True)
class MarkdownBlock:
    block_id: str
    kind: str
    start: int
    end: int
    raw: str
    translatable: bool


@dataclass(frozen=True)
class TranslationBudget:
    max_source_chars: int = DEFAULT_MAX_SOURCE_CHARS
    max_estimated_tokens: int = DEFAULT_MAX_ESTIMATED_TOKENS
    max_blocks: int = DEFAULT_MAX_BLOCKS
    max_blocks_per_chunk: int = DEFAULT_MAX_BLOCKS_PER_CHUNK
    max_chars_per_chunk: int = DEFAULT_MAX_CHARS_PER_CHUNK
    max_tokens_per_chunk: int = DEFAULT_MAX_TOKENS_PER_CHUNK
    max_translation_chunks: int = DEFAULT_MAX_TRANSLATION_CHUNKS
    max_ai_attempts: int = DEFAULT_MAX_AI_ATTEMPTS

    def validate(self) -> "TranslationBudget":
        values = asdict(self)
        invalid = {name: value for name, value in values.items() if not isinstance(value, int) or value <= 0}
        if invalid:
            raise SkillError("INVALID_INPUT", "Translation-budget values must be positive integers.", invalid=invalid)
        return self


def workspace_root_from_script() -> Path:
    return Path(__file__).resolve().parents[6]


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def estimate_tokens(text: str) -> int:
    """Conservative deterministic context estimate without an external tokenizer."""

    return max(1, (len(text.encode("utf-8")) + 3) // 4)


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
        raise SkillError("INVALID_INPUT", "JSON file is missing or malformed.", path=str(path), reason=str(exc))
    if not isinstance(value, dict):
        raise SkillError("INVALID_INPUT", "JSON input must contain an object.", path=str(path))
    return value


def _mapping(value: Union[Mapping[str, Any], Path, str]) -> Tuple[Dict[str, Any], Optional[Path]]:
    if isinstance(value, Mapping):
        return dict(value), None
    path = Path(value).resolve()
    return read_json(path), path


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _safe_path(value: Any, root: Path, *, field: str, must_exist: bool = True) -> Path:
    if not isinstance(value, str) or not value:
        raise SkillError("HANDOFF_SCHEMA_INVALID", "Converter handoff path is missing.", field=field)
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise SkillError("HANDOFF_SCHEMA_INVALID", "Converter handoff path must be absolute and non-symlinked.", field=field, path=value)
    resolved = path.resolve()
    if not _is_relative_to(resolved, root):
        raise SkillError("SOURCE_IDENTITY_MISMATCH", "Converter handoff path escapes the workspace.", field=field, path=value)
    if must_exist and not resolved.exists():
        code = "PAPER_FOLDER_MISSING" if field == "paper_folder" else "ORIGINAL_MD_MISSING" if field == "original_md" else "HANDOFF_NOT_FOUND"
        raise SkillError(code, "Required converter handoff artifact is missing.", field=field, path=value)
    return resolved


def _select_handoff_item(handoff: Mapping[str, Any]) -> Mapping[str, Any]:
    if handoff.get("error_code") == "MULTIPLE_PDFS_DISCOVERED" or int(handoff.get("pdf_count", 0) or 0) > 1:
        raise SkillError("MULTIPLE_PDFS_DISCOVERED", "Exactly one converted paper is required.")
    results = handoff.get("results")
    if isinstance(results, list):
        candidates = [item for item in results if isinstance(item, dict) and item.get("status") in {"success", "skipped"}]
        if not candidates:
            raise SkillError("CONVERSION_NOT_SUCCESSFUL", "Converter produced no successful paper handoff.")
        if len(candidates) != 1:
            raise SkillError("MULTIPLE_PDFS_DISCOVERED", "Exactly one successful converted paper is required.", count=len(candidates))
        return candidates[0]
    if handoff.get("schema_version") == MANIFEST_SCHEMA_VERSION:
        return handoff
    if handoff.get("manifest"):
        return handoff
    raise SkillError("HANDOFF_NOT_FOUND", "Converter result or manifest could not be resolved.")


def resolve_converted_paper(
    url_path: str,
    converter_handoff: Union[Mapping[str, Any], Path, str],
    *,
    workspace_root: Optional[Path] = None,
) -> Dict[str, Any]:
    if not isinstance(url_path, str) or not url_path.strip():
        raise SkillError("INVALID_INPUT", "url_path must be a non-empty string.")
    root = (workspace_root or workspace_root_from_script()).resolve()
    handoff, handoff_path = _mapping(converter_handoff)
    item = _select_handoff_item(handoff)

    if handoff.get("status") == "error":
        raise SkillError("CONVERSION_NOT_SUCCESSFUL", "Converter result is not successful.")

    manifest_value = item.get("manifest")
    if handoff_path and handoff.get("schema_version") == MANIFEST_SCHEMA_VERSION:
        manifest_path = handoff_path
    else:
        manifest_path = _safe_path(manifest_value, root, field="manifest")
    if manifest_path.name != ".conversion-manifest.json" or not manifest_path.is_file():
        raise SkillError("HANDOFF_NOT_FOUND", "Converter manifest is missing or has an invalid filename.", path=str(manifest_path))
    manifest = read_json(manifest_path)
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise SkillError("HANDOFF_SCHEMA_INVALID", "Converter manifest schema is unsupported.", schema_version=manifest.get("schema_version"))
    if manifest.get("status") != "success" or str(manifest.get("conversion_status", "")).upper() != "SUCCESS":
        raise SkillError("CONVERSION_NOT_SUCCESSFUL", "Converter manifest does not record a complete success.")
    if manifest.get("url_path") != url_path:
        raise SkillError("SOURCE_IDENTITY_MISMATCH", "url_path does not match the converter manifest.", requested=url_path, recorded=manifest.get("url_path"))

    renamed_pdf = _safe_path(manifest.get("renamed_pdf"), root, field="renamed_pdf")
    paper_folder = _safe_path(manifest.get("paper_folder"), root, field="paper_folder")
    original_md = _safe_path(manifest.get("original_md"), root, field="original_md")
    asset_dir = _safe_path(manifest.get("asset_dir"), root, field="asset_dir")
    expected_manifest = paper_folder / ".conversion-manifest.json"
    if manifest_path != expected_manifest or manifest.get("manifest") != str(manifest_path):
        raise SkillError("HANDOFF_SCHEMA_INVALID", "Manifest path does not match its paper folder.", path=str(manifest_path))
    if original_md != paper_folder / "original.md" or asset_dir != paper_folder / "Asset":
        raise SkillError("HANDOFF_SCHEMA_INVALID", "Converter artifact paths do not match the paper folder.")
    if renamed_pdf != paper_folder.with_suffix(".pdf"):
        raise SkillError("HANDOFF_SCHEMA_INVALID", "Renamed PDF is not the sibling of its paper folder.")
    if not renamed_pdf.is_file() or renamed_pdf.read_bytes()[:5] != b"%PDF-":
        raise SkillError("HANDOFF_NOT_FOUND", "Renamed PDF is missing or invalid.", path=str(renamed_pdf))
    if not original_md.is_file() or not original_md.read_text(encoding="utf-8").strip():
        raise SkillError("ORIGINAL_MD_MISSING", "original.md is missing or empty.", path=str(original_md))
    if not asset_dir.is_dir():
        raise SkillError("HANDOFF_NOT_FOUND", "Asset directory is missing.", path=str(asset_dir))

    source_hash = sha256_file(renamed_pdf)
    original_hash = sha256_file(original_md)
    if source_hash != manifest.get("source_sha256") or original_hash != manifest.get("original_md_sha256"):
        raise SkillError("SOURCE_HASH_MISMATCH", "Converter source or original.md hash changed after conversion.")
    artifacts = manifest.get("artifact_hashes")
    if not isinstance(artifacts, dict) or artifacts.get("original.md") != original_hash:
        raise SkillError("HANDOFF_SCHEMA_INVALID", "Converter artifact hash inventory is incomplete.")
    for relative, expected_hash in artifacts.items():
        artifact = (paper_folder / relative).resolve()
        if not _is_relative_to(artifact, paper_folder) or not artifact.is_file() or sha256_file(artifact) != expected_hash:
            raise SkillError("SOURCE_HASH_MISMATCH", "Converter artifact hash validation failed.", artifact=relative)

    language = manifest.get("source_language")
    if not isinstance(language, dict) or not isinstance(language.get("language"), str) or not isinstance(language.get("confidence"), (int, float)):
        raise SkillError("HANDOFF_SCHEMA_INVALID", "Source-language decision is missing from the converter manifest.")
    if float(language["confidence"]) < MIN_LANGUAGE_CONFIDENCE:
        raise SkillError("CONVERSION_NOT_SUCCESSFUL", "Source language was not classified confidently enough.")

    return {
        "status": "success",
        "url_path": url_path,
        "workspace_root": str(root),
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "renamed_pdf": str(renamed_pdf),
        "paper_folder": str(paper_folder),
        "original_md": str(original_md),
        "asset_dir": str(asset_dir),
        "source_sha256": source_hash,
        "original_md_sha256": original_hash,
        "source_language": {"language": language["language"].lower().split("-")[0], "confidence": float(language["confidence"])},
    }


def _deny_existing_outputs(paper_folder: Path) -> None:
    existing = [str(path) for path in (paper_folder / "voice-tone.md", paper_folder / "vie.md") if path.exists()]
    if existing:
        raise SkillError("OUTPUT_EXISTS", "Translator outputs already exist and replacement is denied.", paths=existing)


def approval_payload(resolved: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "schema_version": APPROVAL_SCHEMA_VERSION,
        "url_path": resolved["url_path"],
        "source_sha256": resolved["source_sha256"],
        "original_md_sha256": resolved["original_md_sha256"],
        "manifest_sha256": resolved["manifest_sha256"],
        "renamed_pdf": resolved["renamed_pdf"],
        "original_md": resolved["original_md"],
        "paper_folder": resolved["paper_folder"],
    }


def approval_token(payload: Mapping[str, Any]) -> str:
    return "APPROVE-TRANSLATE-TO-VIE:" + sha256_bytes(_canonical_json(payload))


def create_approval_state(
    resolved: Mapping[str, Any],
    *,
    workspace_root: Optional[Path] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    root = (workspace_root or Path(str(resolved.get("workspace_root")))).resolve()
    resolved = _revalidate_resolved(resolved)
    paper_folder = _safe_path(resolved.get("paper_folder"), root, field="paper_folder")
    _deny_existing_outputs(paper_folder)
    payload = approval_payload(resolved)
    token = approval_token(payload)
    state_dir = root / ".agents" / "scratch" / "ux-research-paper" / (run_id or uuid.uuid4().hex)
    state_dir.mkdir(parents=True, exist_ok=False)
    state_path = state_dir / "approval.json"
    state = {
        "schema_version": APPROVAL_SCHEMA_VERSION,
        "status": "awaiting_approval",
        "approval_token": token,
        "payload": payload,
        "resolved": dict(resolved),
        "approval_state": str(state_path),
    }
    atomic_write_json(state_path, state)
    return {
        "status": "awaiting_approval",
        "approval_token": token,
        "approval_state": str(state_path),
        "renamed_pdf": resolved["renamed_pdf"],
        "original_md": resolved["original_md"],
        "asset_dir": resolved["asset_dir"],
        "manifest": resolved["manifest"],
        "expected_outputs": [str(paper_folder / "voice-tone.md"), str(paper_folder / "vie.md")],
    }


def _approved_response(response: str, token: str) -> bool:
    lowered = str(response or "").casefold()
    return token.casefold() in lowered and any(word in lowered for word in AFFIRMATIVE_WORDS)


def _remove_owned_dir(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def _revalidate_resolved(resolved: Mapping[str, Any]) -> Dict[str, Any]:
    current = resolve_converted_paper(
        str(resolved["url_path"]),
        Path(str(resolved["manifest"])),
        workspace_root=Path(str(resolved["workspace_root"])),
    )
    if approval_payload(current) != approval_payload(resolved):
        raise SkillError("APPROVAL_INVALID", "Converter artifacts changed after approval was requested.")
    return current


def consume_approval(approval_state_path: Path, response: str) -> Dict[str, Any]:
    path = approval_state_path.resolve()
    state = read_json(path)
    if state.get("schema_version") != APPROVAL_SCHEMA_VERSION or state.get("status") != "awaiting_approval":
        raise SkillError("APPROVAL_INVALID", "Approval state is invalid or already consumed.", path=str(path))
    token = state.get("approval_token")
    if not isinstance(token, str) or not _approved_response(response, token):
        raise SkillError("NOT_APPROVED", "Translation requires an affirmative response containing the exact approval token.")
    resolved = state.get("resolved")
    if not isinstance(resolved, dict):
        raise SkillError("APPROVAL_INVALID", "Approval state lacks the converter handoff.")
    try:
        current = _revalidate_resolved(resolved)
    except SkillError as exc:
        _remove_owned_dir(path.parent)
        raise SkillError("APPROVAL_INVALID", "Approved converter artifacts changed.", cause=exc.code)
    if approval_token(approval_payload(current)) != token or state.get("payload") != approval_payload(current):
        _remove_owned_dir(path.parent)
        raise SkillError("APPROVAL_INVALID", "Approval token no longer matches current converter artifacts.")
    state["status"] = "approved"
    state["resolved"] = current
    atomic_write_json(path, state)
    return state


FENCE_RE = re.compile(r"^\s*(```+|~~~+)")
TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+(?:\s*:?-{3,}:?\s*\|?)\s*$")
REFERENCE_RE = re.compile(r"^\s*\[(?:\d+|[A-Za-z][\w.-]*)\]\s+")
REFERENCE_DEFINITION_RE = re.compile(r"^\s*\[[^\]]+\]:\s*\S+")
SETEXT_UNDERLINE_RE = re.compile(r"^\s*(?:=+|-+)\s*$")
HTML_LINE_RE = re.compile(r"^\s*</?[A-Za-z][^>]*>")


def _line_kind(text: str) -> Tuple[str, bool]:
    stripped = text.strip()
    if not stripped:
        return "blank", False
    if TABLE_SEPARATOR_RE.match(text):
        return "table_separator", False
    if REFERENCE_DEFINITION_RE.match(text):
        return "reference_definition", False
    if REFERENCE_RE.match(text):
        return "reference", False
    if re.match(r"^\s*(?:---+|___+|\*\*\*+)\s*$", text):
        return "thematic_break", False
    if stripped.startswith("$$") and stripped.endswith("$$"):
        return "formula", False
    if re.match(r"^#{1,6}\s+", text):
        return "heading", True
    if stripped.startswith("|") and stripped.endswith("|"):
        return "table_row", True
    if re.match(r"^\s*(?:[-+*]|\d+[.)])\s+", text):
        return "list_item", True
    if re.match(r"^\s*>+\s?", text):
        return "blockquote", True
    if re.search(r"!\[[^\]]*\]\([^)]+\)", text):
        return "image", True
    if HTML_LINE_RE.match(text):
        visible = re.sub(r"<[^>]+>", "", text)
        return "html_block", any(character.isalpha() for character in visible)
    return "paragraph", any(character.isalpha() for character in text)


def parse_markdown_blocks(markdown: str) -> List[MarkdownBlock]:
    blocks: List[MarkdownBlock] = []
    lines = markdown.splitlines(keepends=True)
    offset = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        content = line.rstrip("\r\n")
        newline_length = len(line) - len(content)
        fence = FENCE_RE.match(content)
        if fence:
            marker = fence.group(1)
            start = offset
            raw_parts = [line]
            offset += len(line)
            index += 1
            while index < len(lines):
                part = lines[index]
                raw_parts.append(part)
                offset += len(part)
                index += 1
                if re.match(r"^\s*%s\s*$" % re.escape(marker[0:3]), part.rstrip("\r\n")):
                    break
            raw = "".join(raw_parts)
            blocks.append(MarkdownBlock("b%06d" % (len(blocks) + 1), "code_fence", start, start + len(raw), raw, False))
            continue
        if content.strip() == "$$":
            start = offset
            raw_parts = [line]
            offset += len(line)
            index += 1
            while index < len(lines):
                part = lines[index]
                raw_parts.append(part)
                offset += len(part)
                index += 1
                if part.rstrip("\r\n").strip() == "$$":
                    break
            raw = "".join(raw_parts)
            blocks.append(MarkdownBlock("b%06d" % (len(blocks) + 1), "math_block", start, start + len(raw), raw, False))
            continue
        if content.strip():
            next_content = lines[index + 1].rstrip("\r\n") if index + 1 < len(lines) else ""
            if SETEXT_UNDERLINE_RE.match(next_content) and not TABLE_SEPARATOR_RE.match(next_content):
                kind, translatable = "setext_heading", True
            elif SETEXT_UNDERLINE_RE.match(content) and blocks and blocks[-1].kind == "setext_heading":
                kind, translatable = "setext_underline", False
            elif re.match(r"^\s{2,}\S", content) and blocks and blocks[-1].kind in {"list_item", "list_continuation"}:
                kind, translatable = "list_continuation", any(character.isalpha() for character in content)
            else:
                kind, translatable = _line_kind(content)
            blocks.append(
                MarkdownBlock(
                    "b%06d" % (len(blocks) + 1),
                    kind,
                    offset,
                    offset + len(content),
                    content,
                    translatable,
                )
            )
        offset += len(content) + newline_length
        index += 1
    return blocks


def _tokens(text: str) -> Counter:
    values: List[str] = []
    patterns = {
        "url": r"https?://[^\s)>\]]+",
        "doi": r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b",
        "citation": r"\[(?:\d+[;,\-\s]*)+\]|\[@[^\]]+\]",
        "target": r"(?<=[\]])\(([^)]+)\)",
        "code": r"`[^`]+`",
        "math": r"\$\$.*?\$\$|(?<!\\)\$[^$\n]+(?<!\\)\$",
        "html": r"</?[A-Za-z][^>]*>",
        "measure": r"(?<![\w])[-+]?\d+(?:[.,]\d+)*(?:\s*(?:%|°[CF]|kg|g|mg|km|m|cm|mm|s|ms|Hz|kHz|MHz|GB|MB|KB))?",
        "identifier": r"\b[A-Z][A-Z0-9_-]{1,}\b",
        "escape": r"\\[|*_{}\[\]()#+.!>-]",
    }
    for label, pattern in patterns.items():
        for match in re.finditer(pattern, text, flags=re.IGNORECASE if label == "doi" else 0):
            captured = match.group(1) if label == "target" else match.group(0)
            values.append(label + ":" + captured)
    return Counter(values)


def _shape(block: MarkdownBlock, text: Optional[str] = None) -> Dict[str, Any]:
    value = block.raw if text is None else text
    heading = re.match(r"^(\s*#{1,6}\s+)", value)
    list_prefix = re.match(r"^(\s*(?:[-+*]|\d+[.)])\s+)", value)
    quote_prefix = re.match(r"^(\s*>+\s?)", value)
    indent_prefix = re.match(r"^(\s+)", value)
    custom_kinds = {"setext_heading", "list_continuation", "html_block"}
    unescaped_pipes = len(re.findall(r"(?<!\\)\|", value))
    return {
        "kind": block.kind if block.kind in custom_kinds else _line_kind(value)[0] if block.kind != "code_fence" else "code_fence",
        "heading_prefix": heading.group(1) if heading else None,
        "list_prefix": list_prefix.group(1) if list_prefix else None,
        "quote_prefix": quote_prefix.group(1) if quote_prefix else None,
        "indent_prefix": indent_prefix.group(1) if block.kind == "list_continuation" and indent_prefix else None,
        "pipe_count": unescaped_pipes if block.kind in {"table_row", "table_separator"} else None,
        "targets": re.findall(r"(?<=[\]])\(([^)]+)\)", value),
        "tokens": sorted(_tokens(value).items()),
    }


def markdown_signature(markdown: str) -> Dict[str, Any]:
    blocks = parse_markdown_blocks(markdown)
    return {
        "block_kinds": [block.kind for block in blocks],
        "block_shapes": [_shape(block) for block in blocks],
        "code_fences": [sha256_bytes(block.raw.encode("utf-8")) for block in blocks if block.kind == "code_fence"],
        "newline_count": markdown.count("\n"),
        "final_newline": markdown.endswith("\n"),
        "tokens": sorted(_tokens(markdown).items()),
    }


def validate_markdown_parity(original: str, vietnamese: str) -> Dict[str, Any]:
    source_signature = markdown_signature(original)
    target_signature = markdown_signature(vietnamese)
    mismatches = [field for field in source_signature if source_signature[field] != target_signature[field]]
    if mismatches:
        token_only = mismatches == ["tokens"]
        code = "PROTECTED_TOKEN_CHANGED" if token_only else "MARKDOWN_STRUCTURE_MISMATCH"
        raise SkillError(code, "Vietnamese Markdown changed protected structure or content.", mismatches=mismatches)
    return {"original": source_signature, "vietnamese": target_signature}


def _looks_vietnamese(values: Iterable[str]) -> bool:
    text = " ".join(values).casefold()
    markers = ("giọng", "văn", "dịch", "ngữ", "trình", "độ", "câu", "thuật ngữ", "không được")
    return sum(marker in text for marker in markers) >= 2


VOICE_PROFILE_FIELDS = (
    "ngoi_ke",
    "muc_do_trang_trong",
    "lap_truong_hoc_thuat",
    "muc_do_chac_chan",
    "nhip_va_cau_truc_cau",
    "mat_do_dien_dat",
    "van_phong_chuyen_nganh",
    "lap_luan_va_bang_chung",
)


def validate_voice_response(
    response: Mapping[str, Any],
    resolved: Mapping[str, Any],
    blocks: Sequence[MarkdownBlock],
) -> Dict[str, Any]:
    if response.get("schema_version") != VOICE_SCHEMA_VERSION or response.get("language") != "vi":
        raise SkillError("VOICE_TONE_SCHEMA_INVALID", "Voice-tone response schema/language is invalid.")
    if response.get("source_sha256") != resolved["source_sha256"] or response.get("original_md_sha256") != resolved["original_md_sha256"]:
        raise SkillError("SOURCE_HASH_MISMATCH", "Voice-tone response targets different source content.")
    expected_ids = [block.block_id for block in blocks]
    if response.get("source_block_ids") != expected_ids:
        raise SkillError("VOICE_TONE_COVERAGE_FAILED", "Voice-tone analysis does not cover every source block in order.")
    profile = response.get("profile")
    if not isinstance(profile, dict) or any(not isinstance(profile.get(field), str) or not profile[field].strip() for field in VOICE_PROFILE_FIELDS):
        raise SkillError("VOICE_TONE_SCHEMA_INVALID", "Voice profile is missing required fields.")
    rules = response.get("translation_rules")
    protected = response.get("protected_content_rules")
    terms = response.get("preferred_terms")
    if not isinstance(rules, list) or not rules or not all(isinstance(item, str) and item.strip() for item in rules):
        raise SkillError("VOICE_TONE_SCHEMA_INVALID", "Translation rules must be a non-empty string list.")
    if not isinstance(protected, list) or not protected or not all(isinstance(item, str) and item.strip() for item in protected):
        raise SkillError("VOICE_TONE_SCHEMA_INVALID", "Protected-content rules must be a non-empty string list.")
    if not isinstance(terms, list) or not all(
        isinstance(item, dict)
        and isinstance(item.get("source_term"), str)
        and isinstance(item.get("vietnamese"), str)
        and isinstance(item.get("note", ""), str)
        for item in terms
    ):
        raise SkillError("VOICE_TONE_SCHEMA_INVALID", "Preferred terms must follow the required schema.")
    if not _looks_vietnamese(list(profile.values()) + list(rules) + list(protected)):
        raise SkillError("VOICE_TONE_NOT_VIETNAMESE", "Voice-tone analysis must be written in Vietnamese.")
    return dict(response)


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def render_voice_tone(response: Mapping[str, Any], resolved: Mapping[str, Any]) -> str:
    profile = response["profile"]
    labels = {
        "ngoi_ke": "Ngôi kể",
        "muc_do_trang_trong": "Mức độ trang trọng",
        "lap_truong_hoc_thuat": "Lập trường học thuật",
        "muc_do_chac_chan": "Mức độ chắc chắn",
        "nhip_va_cau_truc_cau": "Nhịp và cấu trúc câu",
        "mat_do_dien_dat": "Mật độ diễn đạt",
        "van_phong_chuyen_nganh": "Văn phong chuyên ngành",
        "lap_luan_va_bang_chung": "Cách lập luận và trình bày bằng chứng",
    }
    lines = [
        "# Phân tích giọng văn và sắc thái",
        "",
        "## Metadata",
        "",
        "- `schema_version`: %s" % VOICE_SCHEMA_VERSION,
        "- `source_language`: %s" % resolved["source_language"]["language"],
        "- `source_block_count`: %d" % len(response["source_block_ids"]),
        "- `analysis_language`: vi",
        "- `source_sha256`: %s" % resolved["source_sha256"],
        "- `original_md_sha256`: %s" % resolved["original_md_sha256"],
        "",
        "## Hồ sơ giọng văn",
        "",
    ]
    lines.extend("- **%s:** %s" % (labels[field], profile[field].strip()) for field in VOICE_PROFILE_FIELDS)
    lines.extend(["", "## Quy tắc dịch bắt buộc", ""])
    lines.extend("%d. %s" % (index, rule.strip()) for index, rule in enumerate(response["translation_rules"], start=1))
    lines.extend(["", "## Thuật ngữ ưu tiên", "", "| Thuật ngữ gốc | Cách dịch ưu tiên | Ghi chú sử dụng |", "| --- | --- | --- |"])
    if response["preferred_terms"]:
        for item in response["preferred_terms"]:
            lines.append("| %s | %s | %s |" % (_escape_table(item["source_term"]), _escape_table(item["vietnamese"]), _escape_table(item.get("note", ""))))
    else:
        lines.append("| Không có thuật ngữ bắt buộc bổ sung | — | Giữ nhất quán theo ngữ cảnh chuyên ngành |")
    lines.extend(["", "## Nội dung không được thay đổi", ""])
    lines.extend("- " + item.strip() for item in response["protected_content_rules"])
    lines.extend(["", "## Phạm vi phân tích", "", "- **Các block đã phân tích:** " + ", ".join(response["source_block_ids"]), "- **Đã bao phủ toàn bộ original.md:** có", ""])
    return "\n".join(lines)


def validate_translation_response(
    response: Mapping[str, Any],
    resolved: Mapping[str, Any],
    blocks: Sequence[MarkdownBlock],
    expected_block_ids: Optional[Sequence[str]] = None,
) -> Dict[str, str]:
    if response.get("schema_version") != TRANSLATION_SCHEMA_VERSION:
        raise SkillError("TRANSLATION_SCHEMA_INVALID", "Translation response schema is invalid.")
    if response.get("source_sha256") != resolved["source_sha256"] or response.get("original_md_sha256") != resolved["original_md_sha256"]:
        raise SkillError("SOURCE_HASH_MISMATCH", "Translation response targets different source content.")
    items = response.get("blocks")
    if not isinstance(items, list):
        raise SkillError("TRANSLATION_SCHEMA_INVALID", "Translation blocks must be a list.")
    selected = set(expected_block_ids) if expected_block_ids is not None else None
    expected = [block for block in blocks if block.translatable and (selected is None or block.block_id in selected)]
    actual_ids = [item.get("block_id") for item in items if isinstance(item, dict)]
    expected_ids = [block.block_id for block in expected]
    if len(actual_ids) != len(set(actual_ids)):
        raise SkillError("TRANSLATION_BLOCK_DUPLICATE", "A source block was translated more than once.")
    missing = [block_id for block_id in expected_ids if block_id not in actual_ids]
    extra = [block_id for block_id in actual_ids if block_id not in expected_ids]
    if missing:
        raise SkillError("TRANSLATION_BLOCK_MISSING", "One or more source blocks are missing.", block_ids=missing)
    if extra:
        raise SkillError("TRANSLATION_BLOCK_SPLIT", "Translation contains unknown extra blocks.", block_ids=extra)
    if actual_ids != expected_ids:
        raise SkillError("TRANSLATION_BLOCK_REORDERED", "Translation block order differs from the source.")
    translated: Dict[str, str] = {}
    for block, item in zip(expected, items):
        if not isinstance(item, dict) or item.get("kind") != block.kind or not isinstance(item.get("translated_text"), str):
            raise SkillError("TRANSLATION_SCHEMA_INVALID", "Translation block kind/text is invalid.", block_id=block.block_id)
        text = item["translated_text"]
        if not text.strip() or "\n" in text or "\r" in text:
            raise SkillError("TRANSLATION_BLOCK_SPLIT", "Each translated block must remain one non-empty source line.", block_id=block.block_id)
        source_shape = _shape(block)
        target_shape = _shape(block, text)
        if source_shape["tokens"] != target_shape["tokens"]:
            raise SkillError("PROTECTED_TOKEN_CHANGED", "A protected token changed.", block_id=block.block_id)
        shape_fields = ("kind", "heading_prefix", "list_prefix", "quote_prefix", "indent_prefix", "pipe_count", "targets")
        if any(source_shape[field] != target_shape[field] for field in shape_fields):
            raise SkillError("MARKDOWN_STRUCTURE_MISMATCH", "Translated block changed Markdown structure.", block_id=block.block_id)
        translated[block.block_id] = text
    return translated


def reassemble_markdown(original: str, blocks: Sequence[MarkdownBlock], translated: Mapping[str, str]) -> str:
    result = original
    for block in reversed(blocks):
        if block.block_id in translated:
            result = result[: block.start] + translated[block.block_id] + result[block.end :]
    return result


def validate_audit(response: Mapping[str, Any], resolved: Mapping[str, Any]) -> None:
    if response.get("schema_version") != AUDIT_SCHEMA_VERSION:
        raise SkillError("AI_AUDIT_FAILED", "Translation audit schema is invalid.", failure_kind="schema")
    if response.get("source_sha256") != resolved["source_sha256"] or response.get("original_md_sha256") != resolved["original_md_sha256"]:
        raise SkillError("SOURCE_HASH_MISMATCH", "Translation audit targets different source content.")
    issues = response.get("issues")
    if response.get("passed") is not True or not isinstance(issues, list) or issues:
        raise SkillError("AI_AUDIT_FAILED", "Built-in AI found unresolved translation issues.", issues=issues, failure_kind="content")


def _load_state(state_path: Path, expected_status: str) -> Dict[str, Any]:
    path = state_path.resolve()
    state = read_json(path)
    if state.get("skill_version") != SKILL_VERSION or state.get("status") != expected_status:
        raise SkillError("INVALID_JOB_STATE", "Translation state is invalid for this phase.", expected=expected_status, actual=state.get("status"))
    state["state_path"] = str(path)
    return state


def _save_state(state: Mapping[str, Any]) -> None:
    path = Path(str(state["state_path"])).resolve()
    atomic_write_json(path, {key: value for key, value in state.items() if key != "state_path"})


VOICE_RETRYABLE_CODES = {
    "VOICE_TONE_SCHEMA_INVALID",
    "VOICE_TONE_COVERAGE_FAILED",
    "VOICE_TONE_NOT_VIETNAMESE",
}
TRANSLATION_RETRYABLE_CODES = {
    "TRANSLATION_SCHEMA_INVALID",
    "TRANSLATION_BLOCK_DUPLICATE",
    "TRANSLATION_BLOCK_MISSING",
    "TRANSLATION_BLOCK_SPLIT",
    "TRANSLATION_BLOCK_REORDERED",
    "PROTECTED_TOKEN_CHANGED",
    "MARKDOWN_STRUCTURE_MISMATCH",
}


def _preserve_retryable_failure(state: Dict[str, Any], phase: str, exc: SkillError) -> bool:
    limits = state.get("translation_budget")
    max_attempts = int(limits.get("max_ai_attempts", DEFAULT_MAX_AI_ATTEMPTS)) if isinstance(limits, dict) else DEFAULT_MAX_AI_ATTEMPTS
    retry_counts = state.setdefault("retry_counts", {})
    attempt = int(retry_counts.get(phase, 0)) + 1
    retry_counts[phase] = attempt
    state["last_retryable_error"] = {
        "phase": phase,
        "error_code": exc.code,
        "message": exc.message,
        "details": exc.details,
        "attempt": attempt,
        "max_attempts": max_attempts,
    }
    if attempt < max_attempts:
        _save_state(state)
        exc.details.update(
            {
                "retryable": True,
                "attempt": attempt,
                "max_attempts": max_attempts,
                "state_path": state["state_path"],
                "resume_status": state["status"],
            }
        )
        return True
    exc.details.update({"retryable": False, "attempt": attempt, "max_attempts": max_attempts, "retry_exhausted": True})
    _cleanup_state(state)
    return False


def _state_blocks(state: Mapping[str, Any]) -> List[MarkdownBlock]:
    values = state.get("blocks")
    if not isinstance(values, list):
        inventory = state.get("block_inventory")
        if isinstance(inventory, dict) and isinstance(inventory.get("path"), str):
            inventory_path = Path(inventory["path"])
            if inventory_path.is_file() and sha256_file(inventory_path) == inventory.get("sha256"):
                values = read_json(inventory_path).get("blocks")
    if not isinstance(values, list):
        raise SkillError("INVALID_JOB_STATE", "Translation state has no block inventory.")
    return [MarkdownBlock(**item) for item in values]


def _cleanup_state(state: Mapping[str, Any]) -> None:
    root_value = state.get("workspace_root")
    resolved = state.get("resolved")
    if not isinstance(root_value, str) or not root_value or not isinstance(resolved, dict):
        return
    root = Path(root_value).resolve()
    paper_value = resolved.get("paper_folder")
    if not isinstance(paper_value, str) or not paper_value:
        return
    paper_folder = Path(paper_value).resolve()

    staging_value = state.get("staging_dir")
    if isinstance(staging_value, str) and staging_value:
        staging = Path(staging_value).resolve()
        staging_root = paper_folder / ".translation-staging"
        if staging != staging_root and _is_relative_to(staging, staging_root) and staging.exists():
            _remove_owned_dir(staging)
            try:
                staging_root.rmdir()
            except OSError:
                pass

    approval_value = state.get("approval_state")
    if isinstance(approval_value, str) and approval_value:
        approval = Path(approval_value).resolve()
        approval_root = root / ".agents" / "scratch" / "ux-research-paper"
        if approval.name == "approval.json" and _is_relative_to(approval, approval_root) and approval.exists():
            run_dir = approval.parent
            if run_dir != approval_root and _is_relative_to(run_dir, approval_root):
                _remove_owned_dir(run_dir)


def prepare_translation(
    approval_state_path: Path,
    response: str,
    *,
    workspace_root: Optional[Path] = None,
    budget: Optional[TranslationBudget] = None,
) -> Dict[str, Any]:
    approval = consume_approval(approval_state_path, response)
    resolved = approval["resolved"]
    root = (workspace_root or Path(resolved["workspace_root"])).resolve()
    current = _revalidate_resolved(resolved)
    paper_folder = Path(current["paper_folder"])
    _deny_existing_outputs(paper_folder)
    original = Path(current["original_md"]).read_text(encoding="utf-8")
    blocks = parse_markdown_blocks(original)
    if not blocks:
        raise SkillError("ORIGINAL_MD_MISSING", "original.md contains no Markdown blocks.")
    limits = (budget or TranslationBudget()).validate()
    estimated_tokens = estimate_tokens(original)
    if (
        len(original) > limits.max_source_chars
        or estimated_tokens > limits.max_estimated_tokens
        or len(blocks) > limits.max_blocks
    ):
        approval["status"] = "awaiting_approval"
        atomic_write_json(approval_state_path.resolve(), approval)
        raise SkillError(
            "RESOURCE_REVIEW_REQUIRED",
            "The approved paper exceeds the configured translation budget.",
            source_characters=len(original),
            max_source_chars=limits.max_source_chars,
            estimated_tokens=estimated_tokens,
            max_estimated_tokens=limits.max_estimated_tokens,
            block_count=len(blocks),
            max_blocks=limits.max_blocks,
        )
    run_id = uuid.uuid4().hex
    staging_dir = paper_folder / ".translation-staging" / run_id
    staging_dir.mkdir(parents=True, exist_ok=False)
    state_path = staging_dir / "translation-state.json"
    state = {
        "skill_version": SKILL_VERSION,
        "status": "awaiting_voice_tone",
        "run_id": run_id,
        "workspace_root": str(root),
        "resolved": current,
        "approval_state": str(approval_state_path.resolve()),
        "staging_dir": str(staging_dir),
        "translation_budget": asdict(limits),
        "retry_counts": {},
    }
    block_inventory_path = staging_dir / "block-inventory.json"
    atomic_write_json(
        block_inventory_path,
        {
            "schema_version": BLOCK_INVENTORY_VERSION,
            "source_sha256": current["source_sha256"],
            "original_md_sha256": current["original_md_sha256"],
            "block_count": len(blocks),
            "blocks": [asdict(block) for block in blocks],
        },
    )
    state["block_inventory"] = {
        "path": str(block_inventory_path),
        "sha256": sha256_file(block_inventory_path),
        "block_count": len(blocks),
    }
    atomic_write_json(
        staging_dir / "voice-tone-request.json",
        {
            "task": "Analyze the complete author's voice and tone and return actionable Vietnamese translation rules.",
            "response_schema": VOICE_SCHEMA_VERSION,
            "source_sha256": current["source_sha256"],
            "original_md_sha256": current["original_md_sha256"],
            "original_md": {"path": current["original_md"], "sha256": current["original_md_sha256"]},
            "block_inventory": state["block_inventory"],
            "instruction": "Read the referenced files from the workspace; return every block ID in source order without embedding original.md in this request.",
        },
    )
    state["state_path"] = str(state_path)
    _save_state(state)
    state["voice_tone_request"] = str(staging_dir / "voice-tone-request.json")
    return state


def _relevant_terms(voice_response: Mapping[str, Any], blocks: Sequence[MarkdownBlock]) -> List[Dict[str, Any]]:
    source_text = "\n".join(block.raw for block in blocks).casefold()
    terms = voice_response.get("preferred_terms")
    if not isinstance(terms, list):
        return []
    return [dict(item) for item in terms if isinstance(item, dict) and str(item.get("source_term", "")).casefold() in source_text]


def _persist_translation_chunk_plan(state: Dict[str, Any]) -> None:
    staging = Path(state["staging_dir"])
    plan_path = staging / "translation-chunks.json"
    chunks = state.get("translation_chunks") or []
    payload = {
        "schema_version": TRANSLATION_CHUNK_PLAN_VERSION,
        "parallel_safe": True,
        "deterministic_reassembly": True,
        "chunk_count": len(chunks),
        "completed_chunk_ids": [chunk["chunk_id"] for chunk in chunks if chunk.get("completed")],
        "chunks": chunks,
    }
    atomic_write_json(plan_path, payload)
    state["translation_chunk_plan"] = {
        "path": str(plan_path),
        "sha256": sha256_file(plan_path),
        "chunk_count": len(chunks),
    }


def _create_translation_chunks(
    state: Dict[str, Any],
    blocks: Sequence[MarkdownBlock],
    voice_response: Mapping[str, Any],
) -> None:
    limits = TranslationBudget(**state["translation_budget"]).validate()
    translatable = [block for block in blocks if block.translatable]
    grouped: List[List[MarkdownBlock]] = []
    current: List[MarkdownBlock] = []
    current_chars = 0
    current_tokens = 0
    for block in translatable:
        block_chars = len(block.raw)
        block_tokens = estimate_tokens(block.raw)
        if block_chars > limits.max_chars_per_chunk or block_tokens > limits.max_tokens_per_chunk:
            raise SkillError(
                "RESOURCE_REVIEW_REQUIRED",
                "A single Markdown block exceeds the configured translation-chunk context budget.",
                block_id=block.block_id,
                block_characters=block_chars,
                max_chars_per_chunk=limits.max_chars_per_chunk,
                estimated_tokens=block_tokens,
                max_tokens_per_chunk=limits.max_tokens_per_chunk,
            )
        if current and (
            len(current) >= limits.max_blocks_per_chunk
            or current_chars + block_chars > limits.max_chars_per_chunk
            or current_tokens + block_tokens > limits.max_tokens_per_chunk
        ):
            grouped.append(current)
            current = []
            current_chars = 0
            current_tokens = 0
        current.append(block)
        current_chars += block_chars
        current_tokens += block_tokens
    if current:
        grouped.append(current)
    if len(grouped) > limits.max_translation_chunks:
        raise SkillError(
            "RESOURCE_REVIEW_REQUIRED",
            "The paper exceeds the configured translation-chunk budget.",
            chunk_count=len(grouped),
            max_translation_chunks=limits.max_translation_chunks,
        )
    staging = Path(state["staging_dir"])
    request_dir = staging / "translation-requests"
    response_dir = staging / "translation-responses"
    request_dir.mkdir(parents=True, exist_ok=True)
    response_dir.mkdir(parents=True, exist_ok=True)
    chunks: List[Dict[str, Any]] = []
    for index, chunk_blocks in enumerate(grouped, start=1):
        chunk_id = "translation-%04d" % index
        request_path = request_dir / (chunk_id + ".json")
        request = {
            "task": "Translate this bounded block chunk fully into Vietnamese; do not change block IDs, order, Markdown shape, or protected tokens.",
            "response_schema": TRANSLATION_SCHEMA_VERSION,
            "chunk_id": chunk_id,
            "source_sha256": state["resolved"]["source_sha256"],
            "original_md_sha256": state["resolved"]["original_md_sha256"],
            "voice_tone": {"path": str(staging / "voice-tone.md"), "sha256": state["voice_tone_sha256"]},
            "translation_rules": list(voice_response["translation_rules"]),
            "protected_content_rules": list(voice_response["protected_content_rules"]),
            "preferred_terms": _relevant_terms(voice_response, chunk_blocks),
            "blocks": [asdict(block) for block in chunk_blocks],
        }
        atomic_write_json(request_path, request)
        chunks.append(
            {
                "chunk_id": chunk_id,
                "block_ids": [block.block_id for block in chunk_blocks],
                "source_characters": sum(len(block.raw) for block in chunk_blocks),
                "estimated_tokens": sum(estimate_tokens(block.raw) for block in chunk_blocks),
                "request": str(request_path),
                "request_sha256": sha256_file(request_path),
                "response": str(response_dir / (chunk_id + ".json")),
                "completed": False,
            }
        )
    state["translation_chunks"] = chunks
    _persist_translation_chunk_plan(state)


def build_voice_tone(state_path: Path, response: Mapping[str, Any]) -> Dict[str, Any]:
    state = _load_state(state_path, "awaiting_voice_tone")
    try:
        resolved = _revalidate_resolved(state["resolved"])
        paper_folder = Path(resolved["paper_folder"])
        _deny_existing_outputs(paper_folder)
        blocks = _state_blocks(state)
        validated = validate_voice_response(response, resolved, blocks)
        staging = Path(state["staging_dir"])
        voice_path = staging / "voice-tone.md"
        atomic_write_text(voice_path, render_voice_tone(validated, resolved))
        state["voice_tone_sha256"] = sha256_file(voice_path)
        state["voice_tone_response"] = {key: value for key, value in validated.items() if key != "source_block_ids"}
        source_language = resolved["source_language"]["language"]
        if source_language == "vi":
            shutil.copyfile(resolved["original_md"], staging / "vie.md")
            state["status"] = "awaiting_audit"
            _write_audit_request(state)
        else:
            _create_translation_chunks(state, blocks, validated)
            if state["translation_chunks"]:
                state["status"] = "awaiting_translation"
            else:
                shutil.copyfile(resolved["original_md"], staging / "vie.md")
                state["status"] = "awaiting_audit"
                _write_audit_request(state)
        state.pop("last_retryable_error", None)
        _save_state(state)
        return state
    except SkillError as exc:
        if exc.code in VOICE_RETRYABLE_CODES:
            _preserve_retryable_failure(state, "voice_tone", exc)
        else:
            _cleanup_state(state)
        raise


def _write_audit_request(state: Mapping[str, Any]) -> None:
    staging = Path(str(state["staging_dir"]))
    resolved = state["resolved"]
    original_path = Path(resolved["original_md"])
    voice_path = staging / "voice-tone.md"
    vie_path = staging / "vie.md"
    source_blocks = _state_blocks(state)
    target_blocks = parse_markdown_blocks(vie_path.read_text(encoding="utf-8"))
    inventory = []
    for source, target in zip(source_blocks, target_blocks):
        inventory.append(
            {
                "block_id": source.block_id,
                "kind": source.kind,
                "source_sha256": sha256_bytes(source.raw.encode("utf-8")),
                "target_sha256": sha256_bytes(target.raw.encode("utf-8")),
                "protected_signature": sha256_bytes(_canonical_json(dict(_tokens(source.raw))).strip()),
            }
        )
    inventory_path = staging / "audit-inventory.json"
    atomic_write_json(
        inventory_path,
        {
            "schema_version": "translation-audit-inventory-v1",
            "block_count": len(inventory),
            "blocks": inventory,
        },
    )
    sample_ids = [item["block_id"] for item in inventory[:3]]
    sample_ids.extend(item["block_id"] for item in inventory[-3:] if item["block_id"] not in sample_ids)
    atomic_write_json(
        staging / "audit-request.json",
        {
            "task": "Read the referenced files and audit the complete Vietnamese Markdown for omissions, additions, mistranslation, and voice-tone drift.",
            "response_schema": AUDIT_SCHEMA_VERSION,
            "source_sha256": resolved["source_sha256"],
            "original_md_sha256": resolved["original_md_sha256"],
            "original_md": {"path": str(original_path), "sha256": sha256_file(original_path)},
            "voice_tone_md": {"path": str(voice_path), "sha256": sha256_file(voice_path)},
            "vie_md": {"path": str(vie_path), "sha256": sha256_file(vie_path)},
            "audit_inventory": {"path": str(inventory_path), "sha256": sha256_file(inventory_path)},
            "context_sample_block_ids": sample_ids,
            "instruction": "The compact inventory proves deterministic coverage; inspect all three files directly for semantic quality.",
        },
    )


def build_translation(state_path: Path, response: Mapping[str, Any]) -> Dict[str, Any]:
    state = _load_state(state_path, "awaiting_translation")
    chunk_id = str(response.get("chunk_id") or "")
    try:
        resolved = _revalidate_resolved(state["resolved"])
        _deny_existing_outputs(Path(resolved["paper_folder"]))
        blocks = _state_blocks(state)
        chunks = state.get("translation_chunks")
        if not isinstance(chunks, list) or not chunks:
            raise SkillError("INVALID_JOB_STATE", "Translation chunk manifest is missing.")
        if not chunk_id and len(chunks) == 1:
            chunk_id = str(chunks[0]["chunk_id"])
        selected = next((chunk for chunk in chunks if chunk.get("chunk_id") == chunk_id), None)
        if selected is None:
            raise SkillError("TRANSLATION_SCHEMA_INVALID", "Translation response has an unknown or missing chunk_id.", chunk_id=chunk_id)
        translated_chunk = validate_translation_response(response, resolved, blocks, selected["block_ids"])
        normalized = dict(response)
        normalized["chunk_id"] = chunk_id
        response_path = Path(selected["response"])
        atomic_write_json(response_path, normalized)
        selected["completed"] = True
        selected["response_sha256"] = sha256_file(response_path)
        _persist_translation_chunk_plan(state)
        if not all(chunk.get("completed") for chunk in chunks):
            state.pop("last_retryable_error", None)
            _save_state(state)
            state["remaining_chunk_ids"] = [chunk["chunk_id"] for chunk in chunks if not chunk.get("completed")]
            return state

        combined_items: List[Dict[str, Any]] = []
        for chunk in chunks:
            chunk_response = read_json(Path(chunk["response"]))
            if sha256_file(Path(chunk["response"])) != chunk.get("response_sha256"):
                raise SkillError("INVALID_JOB_STATE", "A validated translation chunk response was tampered.", chunk_id=chunk["chunk_id"])
            combined_items.extend(chunk_response["blocks"])
        combined = {
            "schema_version": TRANSLATION_SCHEMA_VERSION,
            "source_sha256": resolved["source_sha256"],
            "original_md_sha256": resolved["original_md_sha256"],
            "blocks": combined_items,
        }
        translated = validate_translation_response(combined, resolved, blocks)
        translated.update(translated_chunk)
        original = Path(resolved["original_md"]).read_text(encoding="utf-8")
        vietnamese = reassemble_markdown(original, blocks, translated)
        validate_markdown_parity(original, vietnamese)
        atomic_write_text(Path(state["staging_dir"]) / "vie.md", vietnamese)
        state["status"] = "awaiting_audit"
        state.pop("last_retryable_error", None)
        _write_audit_request(state)
        _save_state(state)
        return state
    except SkillError as exc:
        if exc.code in TRANSLATION_RETRYABLE_CODES:
            _preserve_retryable_failure(state, "translation:" + (chunk_id or "unknown"), exc)
        else:
            _cleanup_state(state)
        raise


def _exclusive_write_bytes(path: Path, data: bytes) -> None:
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
    except Exception:
        if path.exists():
            path.unlink()
        raise


def _publish_pair(staging: Path, paper_folder: Path) -> None:
    lock = paper_folder / ".translate-to-vie.lock"
    lock_descriptor: Optional[int] = None
    created: List[Path] = []
    try:
        lock_descriptor = os.open(str(lock), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        _deny_existing_outputs(paper_folder)
        for name in ("voice-tone.md", "vie.md"):
            target = paper_folder / name
            _exclusive_write_bytes(target, (staging / name).read_bytes())
            created.append(target)
    except SkillError:
        for path in reversed(created):
            if path.exists():
                path.unlink()
        raise
    except FileExistsError as exc:
        for path in reversed(created):
            if path.exists():
                path.unlink()
        code = "OUTPUT_EXISTS" if Path(exc.filename or "").name in {"voice-tone.md", "vie.md"} else "PUBLICATION_FAILED"
        raise SkillError(code, "Translator output or lock already exists.", path=exc.filename)
    except Exception as exc:
        rollback_failures = []
        for path in reversed(created):
            try:
                if path.exists():
                    path.unlink()
            except Exception as rollback_exc:
                rollback_failures.append({"path": str(path), "reason": str(rollback_exc)})
        if rollback_failures:
            raise SkillError("ROLLBACK_FAILED", "Translator publication rollback failed.", failures=rollback_failures)
        raise SkillError("PUBLICATION_FAILED", "Translator outputs could not be published transactionally.", reason=str(exc))
    finally:
        if lock_descriptor is not None:
            os.close(lock_descriptor)
            if lock.exists():
                lock.unlink()


def _prepare_audit_retry(state: Dict[str, Any], exc: SkillError) -> None:
    if exc.details.get("failure_kind") == "content" and state["resolved"]["source_language"]["language"] != "vi":
        staging = Path(state["staging_dir"])
        for path in (staging / "vie.md", staging / "audit-request.json", staging / "audit-inventory.json"):
            if path.exists():
                path.unlink()
        chunks = state.get("translation_chunks") or []
        for chunk in chunks:
            response_value = chunk.get("response")
            if isinstance(response_value, str) and response_value:
                response_path = Path(response_value)
                if response_path.exists():
                    response_path.unlink()
            chunk["completed"] = False
            chunk.pop("response_sha256", None)
        state["status"] = "awaiting_translation"
        state["audit_feedback"] = list(exc.details.get("issues") or [])
        _persist_translation_chunk_plan(state)
    _preserve_retryable_failure(state, "audit", exc)
    exc.details["resume_status"] = state.get("status")


def publish_translation(state_path: Path, audit_response: Mapping[str, Any]) -> Dict[str, Any]:
    state = _load_state(state_path, "awaiting_audit")
    try:
        resolved = _revalidate_resolved(state["resolved"])
        paper_folder = Path(resolved["paper_folder"])
        _deny_existing_outputs(paper_folder)
        staging = Path(state["staging_dir"])
        voice = staging / "voice-tone.md"
        vietnamese = staging / "vie.md"
        if not voice.is_file() or not vietnamese.is_file() or sha256_file(voice) != state.get("voice_tone_sha256"):
            raise SkillError("INVALID_JOB_STATE", "Staged voice-tone or translation is missing/tampered.")
        original_text = Path(resolved["original_md"]).read_text(encoding="utf-8")
        vietnamese_text = vietnamese.read_text(encoding="utf-8")
        validate_markdown_parity(original_text, vietnamese_text)
        validate_audit(audit_response, resolved)
        _publish_pair(staging, paper_folder)
        result = {
            "status": "success",
            "url_path": resolved["url_path"],
            "paper_folder": str(paper_folder),
            "voice_tone_md": str(paper_folder / "voice-tone.md"),
            "vie_md": str(paper_folder / "vie.md"),
            "source_language": resolved["source_language"]["language"],
            "copied_source": resolved["source_language"]["language"] == "vi",
            "validation": {
                "voice_tone": "passed",
                "coverage": "passed",
                "structure_parity": "passed",
                "audit": "passed",
            },
        }
        _cleanup_state(state)
        return result
    except SkillError as exc:
        if exc.code == "AI_AUDIT_FAILED":
            _prepare_audit_retry(state, exc)
        else:
            _cleanup_state(state)
        raise


def inspect_output(paper_folder: Path) -> Dict[str, Any]:
    folder = paper_folder.resolve()
    original = folder / "original.md"
    voice = folder / "voice-tone.md"
    vietnamese = folder / "vie.md"
    if not original.is_file() or not voice.is_file() or not vietnamese.is_file():
        return {"status": "invalid", "reason": "required_file_missing", "paper_folder": str(folder)}
    try:
        validate_markdown_parity(original.read_text(encoding="utf-8"), vietnamese.read_text(encoding="utf-8"))
    except SkillError as exc:
        return {"status": "invalid", "reason": exc.code, "paper_folder": str(folder)}
    return {
        "status": "valid",
        "paper_folder": str(folder),
        "voice_tone_md": str(voice),
        "vie_md": str(vietnamese),
    }


def _add_translation_budget_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-source-chars", type=int, default=DEFAULT_MAX_SOURCE_CHARS)
    parser.add_argument("--max-estimated-tokens", type=int, default=DEFAULT_MAX_ESTIMATED_TOKENS)
    parser.add_argument("--max-blocks", type=int, default=DEFAULT_MAX_BLOCKS)
    parser.add_argument("--max-blocks-per-chunk", type=int, default=DEFAULT_MAX_BLOCKS_PER_CHUNK)
    parser.add_argument("--max-chars-per-chunk", type=int, default=DEFAULT_MAX_CHARS_PER_CHUNK)
    parser.add_argument("--max-tokens-per-chunk", type=int, default=DEFAULT_MAX_TOKENS_PER_CHUNK)
    parser.add_argument("--max-translation-chunks", type=int, default=DEFAULT_MAX_TRANSLATION_CHUNKS)
    parser.add_argument("--max-ai-attempts", type=int, default=DEFAULT_MAX_AI_ATTEMPTS)


def _translation_budget_from_args(args: argparse.Namespace) -> TranslationBudget:
    return TranslationBudget(
        max_source_chars=args.max_source_chars,
        max_estimated_tokens=args.max_estimated_tokens,
        max_blocks=args.max_blocks,
        max_blocks_per_chunk=args.max_blocks_per_chunk,
        max_chars_per_chunk=args.max_chars_per_chunk,
        max_tokens_per_chunk=args.max_tokens_per_chunk,
        max_translation_chunks=args.max_translation_chunks,
        max_ai_attempts=args.max_ai_attempts,
    ).validate()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    resolve = commands.add_parser("resolve")
    resolve.add_argument("--url-path", required=True)
    resolve.add_argument("--handoff-json", type=Path, required=True)
    resolve.add_argument("--workspace-root", type=Path)

    approval = commands.add_parser("create-approval")
    approval.add_argument("--resolved-json", type=Path, required=True)
    approval.add_argument("--workspace-root", type=Path)

    prepare = commands.add_parser("prepare")
    prepare.add_argument("--approval-state", type=Path, required=True)
    prepare.add_argument("--approval-response", required=True)
    prepare.add_argument("--workspace-root", type=Path)
    _add_translation_budget_arguments(prepare)

    voice = commands.add_parser("build-voice-tone")
    voice.add_argument("--state-json", type=Path, required=True)
    voice.add_argument("--voice-tone-response", type=Path, required=True)

    translation = commands.add_parser("build-translation")
    translation.add_argument("--state-json", type=Path, required=True)
    translation.add_argument("--translation-response", type=Path, required=True)

    publish = commands.add_parser("publish")
    publish.add_argument("--state-json", type=Path, required=True)
    publish.add_argument("--audit-response", type=Path, required=True)

    inspect = commands.add_parser("inspect-output")
    inspect.add_argument("--paper-folder", type=Path, required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "resolve":
            result = resolve_converted_paper(args.url_path, args.handoff_json, workspace_root=args.workspace_root)
        elif args.command == "create-approval":
            result = create_approval_state(read_json(args.resolved_json), workspace_root=args.workspace_root)
        elif args.command == "prepare":
            result = prepare_translation(
                args.approval_state,
                args.approval_response,
                workspace_root=args.workspace_root,
                budget=_translation_budget_from_args(args),
            )
        elif args.command == "build-voice-tone":
            result = build_voice_tone(args.state_json, read_json(args.voice_tone_response))
        elif args.command == "build-translation":
            result = build_translation(args.state_json, read_json(args.translation_response))
        elif args.command == "publish":
            result = publish_translation(args.state_json, read_json(args.audit_response))
        elif args.command == "inspect-output":
            result = inspect_output(args.paper_folder)
        else:
            raise SkillError("INVALID_COMMAND", "Unsupported command.")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result.get("status") not in {"error", "invalid"} else 2
    except SkillError as exc:
        print(json.dumps(exc.to_dict(), ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
