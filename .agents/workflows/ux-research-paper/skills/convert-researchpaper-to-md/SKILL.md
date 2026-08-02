---
name: convert-researchpaper-to-md
description: Convert exactly one local or remote research-paper PDF with Docling into a title-renamed PDF, complete source-language original.md, extracted visual assets, and a validated converter handoff. Use as the first stage of the ux-research-paper workflow before any Vietnamese translation.
---

# Convert Research Paper to Markdown

## Description

Convert exactly one research-paper PDF into complete source-language Markdown with Docling. Discover a local PDF/directory, `file://` source, direct public PDF URL, or public page containing PDF links; require one exact paper; validate its first true title with Built-in AI; rename the PDF; extract layout, OCR text, tables, pictures, formulas, footnotes, references, and appendices; then publish `original.md`, `Asset/`, and a `converter-manifest-v2` handoff.

Run this skill first in `ux-research-paper`. It never creates `voice-tone.md` or `vie.md`; the orchestrator must ask for user approval before invoking `translate-to-vie`.

Prerequisites:

- Python 3.10 or newer.
- Docling `>=2.117.0,<3`.
- Tesseract CLI and language data only when full-page OCR fallback is required.
- Host Built-in AI for title validation, language classification, and source-completeness audit.

Before execution:

```bash
python3 .agents/scripts/check_libraries.py
python3 -B .agents/workflows/ux-research-paper/skills/convert-researchpaper-to-md/scripts/convert_researchpaper_to_md.py check-dependencies
```

## Input

- **Type**: `dict`
- **Format**:

  | Field | Type | Required | Rules |
  | --- | --- | --- | --- |
  | `url_path` | `str` | Yes | Absolute local PDF/directory, `file://` PDF/directory, direct public HTTP(S) PDF, or public same-origin collection page. Exactly one PDF must resolve. |
  | `force` | `bool` | No | Rebuild owned converter artifacts through staging; defaults to `false`. Never touches translator outputs. |
  | `prior_handoff` | `dict` or absolute JSON path | No | Previous converter result/manifest for the same `url_path`. When valid and unchanged, return it before discovery, Docling, or AI. |
  | `resource_budget` | `dict` | No | Positive limits for PDF bytes, pages, staging bytes, audit items/chars per chunk, and audit chunk count. |

- **Location**: `request_body`
- **Input File(s)**:
  - `<arbitrary-name>.pdf` — One research paper; its filename need not match the title.
- **Examples**:

  ```json
  {
    "url_path": "/absolute/workspace/path/paper.pdf",
    "force": false
  }
  ```

If a folder or collection resolves more than one PDF, return `MULTIPLE_PDFS_DISCOVERED` without renaming or converting any paper.

Remote URLs must not contain credentials or resolve to localhost, private, link-local, reserved, or multicast addresses. Stream each PDF into workspace-owned storage while hashing, bound it to 100 MiB by default, require its `%PDF-` signature, and retry only transient connection/timeout/HTTP 429/5xx failures up to three attempts.

## Output

- **Type**: `dict`
- **Format**:

  ```json
  {
    "status": "success|skipped|review_required|error",
    "url_path": "/requested/paper.pdf",
    "source_type": "local_pdf|file_pdf|remote_pdf",
    "pdf_count": 1,
    "succeeded": 1,
    "failed": 0,
    "results": [
      {
        "status": "success",
        "renamed_pdf": "/parent/Validated Paper Title.pdf",
        "output_dir": "/parent/Validated Paper Title",
        "original_md": "/parent/Validated Paper Title/original.md",
        "asset_dir": "/parent/Validated Paper Title/Asset",
        "manifest": "/parent/Validated Paper Title/.conversion-manifest.json",
        "source_language": {"language": "en", "confidence": 0.99},
        "handoff_schema_version": "converter-manifest-v2"
      }
    ]
  }
  ```

- **Location**: `file_path`
- **Output File(s)**:
  - `<validated-title>.pdf` — Source PDF renamed atomically without changing its bytes.
  - `<validated-title>/original.md` — Complete source-language Markdown.
  - `<validated-title>/Asset/` — Every extracted picture/chart and visual table companion.
  - `<validated-title>/.conversion-manifest.json` — Final handoff marker with paths, identities, hashes, source language, asset inventory, and Docling status.

```text
<parent>/
├── Validated Paper Title.pdf
└── Validated Paper Title/
    ├── original.md
    ├── Asset/
    │   ├── page-001-figure-001.png
    │   └── page-003-table-001.png
    └── .conversion-manifest.json
```

The converter must not create, remove, replace, back up, or validate `voice-tone.md` or `vie.md`.

## API Key

| Field | Value | Notes |
| --- | --- | --- |
| **Key** | `None` | Never read `.env`; no external AI API is used. |
| **Model** | `Built-in AI` | The host supplies title, language, and source-audit decisions. |

## Custom Instructions

- Treat `scripts/convert_researchpaper_to_md.py` as the deterministic runtime. Do not replace Docling with AI-generated prose or another PDF converter.
- If `prior_handoff` is supplied and `force=false`, run `inspect-handoff` first. Return the valid current handoff before discovery, title preflight, Docling, or Built-in AI; never trust it without path and hash validation.
- Run `discover` first and require exactly one source before any rename or output mutation.
- Keep remote incoming data only under workspace-owned `.agents/scratch/convert-researchpaper-to-md/`; stream and hash downloads instead of buffering PDFs in memory.
- Retry transient DNS, connection, timeout, HTTP 429, and HTTP 5xx failures with bounded exponential backoff. Never retry blocked hosts, excessive sizes, invalid PDF signatures, or deterministic validation failures.
- Run Docling title preflight on pages 1–3. Select the first non-empty BODY `TITLE`; only if absent, select the first non-generic BODY `SECTION_HEADER`. Exclude furniture, mastheads, headers/footers, DOI banners, authors, affiliations, abstract labels, and introduction labels.
- Ask Built-in AI to confirm the title with exactly:

  ```json
  {"valid": true, "confidence": 0.99, "title": "Exact Paper Title", "reason": "..."}
  ```

- Do not rename below `0.85` title confidence or after a malformed/ambiguous decision.
- Normalize title Unicode to NFC, preserve readable Unicode/spaces, remove unsafe filename characters, retain `.pdf`, and use a deterministic hash suffix for collisions.
- Make the source-PDF rename the first final-output mutation and verify SHA-256 immediately afterward.
- Configure Docling with `do_ocr=True`, `do_table_structure=True`, `TableStructureOptions(do_cell_matching=True)`, `images_scale=2.0`, `generate_page_images=True`, and `generate_picture_images=True`.
- Accept only Docling `ConversionStatus.SUCCESS`. Never publish `PARTIAL_SUCCESS`.
- Run standard hybrid OCR first. If deterministic page/text coverage is insufficient, retry with `TesseractCliOcrOptions(lang=["auto"], mode=OcrMode.FULL_PAGE)`.
- Preserve the lossless `DoclingDocument` inventory as the canonical completeness source.
- Export pictures and visual table companions as PNG with page-and-occurrence filenames in `Asset/`.
- Serialize Markdown with `ImageRefMode.PLACEHOLDER`, replace every image placeholder deterministically, and reject unresolved placeholders.
- Ask Built-in AI to classify source language with exactly:

  ```json
  {"language": "en", "confidence": 0.99, "reason": "..."}
  ```

- Require language confidence of at least `0.85` for the translator handoff.
- Partition the source audit deterministically by Docling item/page IDs under the configured item/character budgets. Built-in AI audits each chunk, then returns one final synthesis with exactly `{"passed": true, "issues": [], "chunk_ids": ["source-audit-0001"], "coverage_complete": true}` covering every ordered chunk ID.
- Enforce PDF-byte, page-count, staging-disk, and audit-chunk budgets. Return `RESOURCE_REVIEW_REQUIRED` with measured and configured limits before resource exhaustion.
- Publish `original.md` and `Asset/` transactionally and write `.conversion-manifest.json` last.
- Write manifest schema `converter-manifest-v2` with the original public `url_path`, source identity, renamed PDF, paper folder, `original.md`, asset directory, source/artifact hashes, source-language decision, Docling status/version, and asset inventory.
- Preserve successful PDF rename when later conversion fails, but publish no `original.md` or success manifest.
- When `force=true`, replace only converter-owned `original.md`, `Asset/`, and manifest; preserve translator outputs and unrelated user files.
- Clean owned preflight, incoming digest, and staging data on every terminal path; include exact removed/retained owned paths in recoverable error details.

Runtime phases:

```bash
python3 -B .agents/workflows/ux-research-paper/skills/convert-researchpaper-to-md/scripts/convert_researchpaper_to_md.py discover --url-path "<url_path>" --workspace-root "<workspace-root>"
python3 -B .agents/workflows/ux-research-paper/skills/convert-researchpaper-to-md/scripts/convert_researchpaper_to_md.py inspect-handoff --url-path "<url_path>" --handoff-json "<prior-result-or-manifest.json>" --workspace-root "<workspace-root>"
python3 -B .agents/workflows/ux-research-paper/skills/convert-researchpaper-to-md/scripts/convert_researchpaper_to_md.py preflight-title --source "<pdf>" --source-kind "<kind>" --original-location "<url_path>" --workspace-root "<workspace-root>"
python3 -B .agents/workflows/ux-research-paper/skills/convert-researchpaper-to-md/scripts/convert_researchpaper_to_md.py prepare --preflight-json "<preflight.json>" --title-decision-json "<title.json>" --workspace-root "<workspace-root>" --max-page-count 500 --max-staging-bytes 1073741824
python3 -B .agents/workflows/ux-research-paper/skills/convert-researchpaper-to-md/scripts/convert_researchpaper_to_md.py publish --job-state "<job-state.json>" --language-decision-json "<language.json>" --audit-json "<audit.json>"
```

## Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Parent as UX Research Paper
    participant Host as Built-in AI
    participant Convert as Converter Python
    participant Docling
    participant FS as Workspace Filesystem

    User->>Parent: url_path
    Parent->>Convert: Inspect optional prior handoff
    alt Prior handoff remains valid
        Convert-->>Parent: Skip with current converter-manifest-v2
    else Conversion required
    Parent->>Convert: Discover exactly one PDF
    Convert->>Docling: Preflight pages 1-3
    Docling-->>Convert: Title candidate and page render
    Convert-->>Host: Title-validation task
    Host-->>Convert: Structured title decision
    Convert->>FS: Atomic PDF rename and hash verification
    Convert->>Docling: Full layout/OCR/table/image conversion
    alt Hybrid OCR coverage insufficient
        Convert->>Docling: Tesseract full-page OCR
    end
    Docling-->>Convert: SUCCESS document and visual assets
    Convert-->>Host: Language and bounded source-audit chunks
    Host-->>Convert: Per-chunk results and complete synthesis
    Convert->>FS: Publish original.md and Asset; manifest last
    Convert-->>Parent: converter-manifest-v2 handoff
    end
    Parent-->>User: Present original.md and request translation approval
```

## Error Handling & Fallbacks

| Error Code | Message | Fallback Behavior |
| --- | --- | --- |
| `INVALID_INPUT` | `url_path` is missing, relative, or unsupported. | Request an absolute local path or valid public URL. |
| `NO_PDFS_DISCOVERED` | No valid PDF was found. | Ask for the correct source. |
| `MULTIPLE_PDFS_DISCOVERED` | More than one PDF was found. | Request one exact PDF URL/path; mutate nothing. |
| `UNSAFE_PATH` | A local path escapes the workspace or uses a symlink. | Reject without mutation. |
| `REMOTE_HOST_BLOCKED` | URL targets credentials or a private/local network. | Request a safe public URL or workspace file. |
| `REMOTE_TOO_LARGE` | Remote input exceeds limits. | Request a smaller/local copy. |
| `REMOTE_FETCH_FAILED` | A transient remote source remained unavailable after bounded retries. | Report attempt count and retry later or use a local PDF. |
| `INVALID_PDF` | File is unreadable or lacks a PDF signature. | Report the exact source. |
| `PYTHON_VERSION_UNSUPPORTED`, `DOCLING_MISSING`, `DOCLING_API_INCOMPATIBLE` | Required runtime is unavailable/incompatible. | Install a supported Python/Docling runtime. |
| `TITLE_NOT_FOUND`, `TITLE_REVIEW_REQUIRED` | No reliable title was confirmed. | Leave source unchanged and request review. |
| `SOURCE_CHANGED`, `SOURCE_HASH_MISMATCH` | PDF identity changed between phases. | Restart discovery and preflight. |
| `DUPLICATE_PDF`, `SOURCE_RENAME_FAILED` | Rename cannot complete safely. | Preserve existing files and report paths. |
| `DOCLING_PREFLIGHT_FAILED`, `DOCLING_PARTIAL_SUCCESS`, `DOCLING_CONVERSION_FAILED` | Docling did not fully succeed. | Publish no source Markdown/manifest. |
| `OCR_DEPENDENCY_MISSING`, `DOCLING_OCR_FAILED`, `CONTENT_INCOMPLETE` | OCR/completeness gate failed. | Install dependencies or require review. |
| `PAGE_RENDER_FAILED`, `ASSET_EXTRACTION_FAILED`, `ASSET_PARITY_FAILED` | Visual inventory is incomplete. | Publish nothing. |
| `LANGUAGE_REVIEW_REQUIRED` | Language confidence is insufficient. | Stop before handoff. |
| `AI_AUDIT_FAILED` | Source audit reports unresolved issues. | Publish nothing until resolved. |
| `RESOURCE_REVIEW_REQUIRED` | PDF/page/staging/audit limits would be exceeded. | Report measured limits and require an explicit smaller input or adjusted budget. |
| `HANDOFF_NOT_FOUND`, `HANDOFF_SCHEMA_INVALID` | A supplied prior handoff is missing or invalid. | Do not skip; provide a current handoff or run a fresh conversion. |
| `PUBLICATION_FAILED` | Transactional final write failed. | Restore prior converter-owned artifacts. |

## Known Bugs & Resolutions

> **Agent Rule:** After successfully fixing a runtime bug, document its cause, resolution, and regression test here.

| Bug / Error | Cause | Resolution |
| --- | --- | --- |
| Test PDF fixture raised `ValueError: unsupported format character 'P'` | Python `%` formatting interpreted `%PDF-` as a format token. | Use f-strings while retaining a literal `%PDF-`; regression fixtures cover it. |
| Remote output parent could be created before title rename | The old remote flow created the final parent too early. | Rename in workspace incoming storage first, then create/persist final output; ordering test retained. |

## Performance Improvement Solutions

### Execution Efficiency

- [x] Add an early handoff/manifest inspection path for an already title-renamed PDF so unchanged successful outputs skip before Docling preflight and title AI; add a regression test proving those adapters are not invoked.
- [x] Split source auditing into bounded chunks keyed by Docling item/page IDs, followed by a final coverage synthesis, so long papers never require one oversized Built-in-AI context.
- [x] Clean owned preflight directories and empty incoming digest directories on every terminal path, with success and failure regression tests.
- [x] Stream remote PDFs into a bounded workspace-owned incoming file while hashing instead of retaining each complete response in memory.

### Workflow Fit

- [x] Let the orchestrator pass a prior manifest/result into the early inspection path and return the current valid handoff without rediscovery or title preflight when all hashes match.

### Reliability & Error Handling

- [x] Centralize owned-scratch cleanup for preflight, remote persistence, success, and failure paths, and include exact retained/removed paths in recoverable errors.
- [x] Add bounded exponential-backoff retries for transient connection, timeout, HTTP 429, and HTTP 5xx failures; never retry blocked hosts, oversized responses, invalid PDF signatures, or terminal validation failures.

### Cost & Scalability

- [x] Add configurable page-count and resource budgets after preflight and before full conversion; return `review_required` with exact exceeded limits instead of exhausting memory or disk.
- [x] Combine streamed downloads with chunked source auditing so memory, disk, and Built-in-AI context usage scale predictably for long papers.
