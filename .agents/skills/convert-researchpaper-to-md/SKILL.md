---
name: convert-researchpaper-to-md
description: Convert one or many local or remote research-paper PDFs with Docling into complete source-language Markdown, extracted visual assets, and a structurally identical Vietnamese translation when needed.
---

# Convert Research Paper to Markdown

## Description

Use this skill when the user asks to convert a research paper, a folder of research-paper PDFs, a direct PDF URL, or a remote page listing PDFs into Markdown. It uses Docling as the primary PDF layout, OCR, table, picture, formula, document-structure, and Markdown engine. Before full conversion, it confirms the first true paper heading with built-in AI, renames the PDF to that title, and only then creates the matching output folder.

The skill fails closed. It does not publish Markdown when title confidence, Docling conversion status, content completeness, extracted assets, source language, translation parity, or the built-in-AI audit is unresolved.

Prerequisites:

- Python 3.10 or newer.
- Docling `>=2.117.0,<3`; this implementation follows the current official [Docling quickstart](https://docling-project.github.io/docling/getting_started/quickstart/), [custom conversion](https://docling-project.github.io/docling/_generated/examples/custom_convert/), [full-page OCR](https://docling-project.github.io/docling/_generated/examples/full_page_ocr/), [figure export](https://docling-project.github.io/docling/_generated/examples/export_figures/), [batch status handling](https://docling-project.github.io/docling/_generated/examples/batch_convert/), and [serialization](https://docling-project.github.io/docling/_generated/examples/serialization/) flows.
- Tesseract CLI plus language data when Docling's standard hybrid OCR fails the text-coverage gate and full-page OCR is required.
- The host agent's built-in AI. No external LLM SDK or API key is used.

Before a run, execute the workspace dependency check and the skill dependency check:

```bash
python3 .agents/scripts/check_libraries.py
python3 -B .agents/skills/convert-researchpaper-to-md/scripts/convert_researchpaper_to_md.py check-dependencies
```

If Docling is missing, install it into a Python 3.10+ runtime:

```bash
python3 -m pip install "docling>=2.117.0,<3"
```

## Input

- **Type**: `dict`
- **Format**:

  | Field | Type | Required | Rules |
  | --- | --- | --- | --- |
  | `url_path` | `str` | Yes | Absolute local PDF/directory, `file://` PDF/directory, direct public HTTP(S) PDF URL, or public HTTP(S) collection page containing same-origin PDF links. |
  | `force` | `bool` | No | Rebuild a prior valid output through staging; defaults to `false`. |

- **Location**: `request_body`
- **Input File(s)**:
  - `<arbitrary-name>.pdf` — One research paper. The current filename does not need to match its paper title.
  - `<url_path>/*.pdf` — Direct children of a local directory; discovery is non-recursive.
- **Examples**:

  **Example 1 — Local folder**

  ```json
  {
    "url_path": "/absolute/workspace/path/research-papers",
    "force": false
  }
  ```

  **Example 2 — Direct remote PDF**

  ```json
  {
    "url_path": "https://example.org/papers/research-paper.pdf"
  }
  ```

Remote URLs must not contain credentials or resolve to localhost, private, link-local, reserved, or multicast addresses. Collection discovery is same-origin, one level, deduplicated, and limited to 50 PDFs. Each response is bounded to 100 MiB and must have a `%PDF-` signature before Docling runs.

## Output

- **Type**: `dict`
- **Format**:

  ```json
  {
    "status": "success|partial_success|review_required|error",
    "url_path": "...",
    "source_type": "local_directory|file_directory|local_pdf|file_pdf|remote_pdf|remote_collection",
    "pdf_count": 2,
    "succeeded": 1,
    "failed": 1,
    "results": [
      {
        "status": "success",
        "renamed_pdf": "/parent/Validated Paper Title.pdf",
        "output_dir": "/parent/Validated Paper Title",
        "original_md": "/parent/Validated Paper Title/original.md",
        "vie_md": "/parent/Validated Paper Title/vie.md",
        "asset_dir": "/parent/Validated Paper Title/Asset",
        "manifest": "/parent/Validated Paper Title/.conversion-manifest.json",
        "source_language": "en"
      }
    ]
  }
  ```

- **Location**: `file_path`
- **Output File(s)**:
  - `<validated-title>.pdf` — The actual local source PDF, or downloaded remote copy, atomically renamed to its validated first heading without changing its bytes.
  - `<validated-title>/original.md` — Complete source-language Markdown generated from Docling's document structure.
  - `<validated-title>/vie.md` — Complete Vietnamese translation; omitted when the source is confidently Vietnamese.
  - `<validated-title>/Asset/` — Every Docling-detected picture/chart and visual table companion, with page-and-occurrence filenames.
  - `<validated-title>/.conversion-manifest.json` — Hidden commit marker containing source/artifact hashes, Docling status/version, asset inventory, language decision, structural signatures, and audit result.

For remote sources, create the renamed downloaded PDF and output folder under `<workspace-root>/output/convert-researchpaper-to-md/`. For local sources, create them beside the source PDF.

```text
<parent>/
├── Validated Paper Title.pdf
└── Validated Paper Title/
    ├── original.md
    ├── vie.md                  # omitted for Vietnamese sources
    ├── Asset/
    │   ├── page-001-figure-001.png
    │   └── page-003-table-001.png
    └── .conversion-manifest.json
```

`original.md` and `vie.md` must share the same heading levels and order, table dimensions, figure links, code fences, formula markers, citations, URLs, DOIs, numbers, and units. Bibliography entries, identifiers, formulas, and numeric tokens remain verbatim. Translate natural-language headings, paragraphs, captions, footnotes, and table cells only.

## API Key

| Field | Value | Notes |
| --- | --- | --- |
| **Key** | `None` | The skill never reads `.env` and requires no external AI API. |
| **Model** | `Built-in AI` | The host provides title validation, language classification, translation, and audit. |

## Custom Instructions

- Treat `.agents/skills/convert-researchpaper-to-md/scripts/convert_researchpaper_to_md.py` as the deterministic runtime. Do not replace Docling extraction with AI prose or another PDF converter.
- Check dependencies before conversion. If Python, Docling, Tesseract, or required Docling models are unavailable for the paper's needed path, stop that paper with the exact dependency error.
- Run `discover` first. Validate hashes and PDF signatures without creating final output folders. Remote downloads may be stored only in the workspace-owned incoming scratch directory.
- Process one paper at a time so title, translation, and audit context cannot leak between papers.
- Run `preflight-title` with Docling on pages 1–3. Select the first non-empty BODY `TITLE`; only if absent, select the first non-generic BODY `SECTION_HEADER`. Exclude furniture, journal mastheads, page headers/footers, DOI banners, authors, affiliations, abstract labels, and introduction labels.
- Inspect the preflight candidate and first-page render with built-in AI. Produce exactly:

  ```json
  {
    "valid": true,
    "confidence": 0.99,
    "title": "Exact Research Paper Title",
    "reason": "The text is the first true paper title on the page."
  }
  ```

- Do not rename when title confidence is below `0.85`, the title is ambiguous, or the AI response is malformed. In that case, leave the PDF unchanged and create no title folder.
- Sanitize the confirmed title with NFC normalization, preserve readable Unicode and spaces, remove unsafe filesystem characters, retain `.pdf`, and use a deterministic source-hash suffix for collisions.
- Make the source-PDF rename the first final-output mutation. Verify its SHA-256 immediately after `os.replace`. Only after this succeeds may the skill create `<renamed-title>/`.
- Follow Docling's documented conversion construction: `PdfPipelineOptions` → `PdfFormatOption` → `DocumentConverter`.
- Configure Docling standard conversion with `do_ocr=True`, `do_table_structure=True`, `TableStructureOptions(do_cell_matching=True)`, `images_scale=2.0`, `generate_page_images=True`, and `generate_picture_images=True`.
- Emit JSON progress events to stderr in CLI mode. The stages are `docling_preflight_configure`, `docling_preflight_convert`, `docling_preflight_complete`, `docling_configure`, `docling_convert`, conditional `docling_full_page_ocr`, `docling_export_page_images`, `docling_export_elements`, and `docling_complete`.
- Accept only Docling `ConversionStatus.SUCCESS`. Convert `PARTIAL_SUCCESS` into review-required/error with Docling diagnostics; never silently publish it.
- Run Docling's standard hybrid OCR first. If deterministic text/page coverage is insufficient, follow the official full-page OCR pattern with `TesseractCliOcrOptions(lang=["auto"], mode=OcrMode.FULL_PAGE)`. If Tesseract is unavailable or the retry remains incomplete, stop the paper.
- Export the lossless `DoclingDocument` with `export_to_dict()` and keep its typed labels, body order, furniture, self-references, provenance, page numbers, tables, pictures, formulas, footnotes, references, and appendices as the canonical inventory.
- Follow Docling's figure-export flow: retain page/picture images, call `PictureItem.get_image(document)` and `TableItem.get_image(document)`, save PNG files through binary file handles, and use page-and-occurrence filenames inside `Asset/`.
- Follow Docling's serialization flow: call `save_as_markdown(..., image_mode=ImageRefMode.PLACEHOLDER)`, replace picture placeholders deterministically with safe relative `Asset/...` links, and reject unresolved placeholders.
- Keep page renders, lossless JSON, and AI task files only under `<output>/.staging/<run-id>/`; do not publish them as user-facing artifacts.
- Ask built-in AI to classify the source language using this exact schema:

  ```json
  {
    "language": "en",
    "confidence": 0.99,
    "reason": "The paper body is English."
  }
  ```

- If the language is confidently `vi`, do not create `vie.md`. If the confidence is below `0.85`, stop for review.
- For non-Vietnamese papers, translate every natural-language field into Vietnamese. Do not summarize, simplify, reorder, merge, split, omit, or invent content. Preserve heading levels, Markdown block order, tables/cell occupancy, image targets, formulas, code, URLs, DOIs, citations, reference entries, identifiers, numbers, and units exactly.
- Ask built-in AI to audit `original.md`, the lossless inventory, extracted assets, and conditional `vie.md`. Produce exactly `{"passed": true, "issues": []}` only when no omission, addition, mistranslation, or structural drift remains.
- Run deterministic structural-signature parity after the AI audit. AI approval cannot override a parity failure.
- Publish through per-paper staging. Back up only owned prior artifacts, move `Asset/`, `original.md`, and conditional `vie.md`, and write `.conversion-manifest.json` last. Roll back owned prior artifacts if publication fails; preserve unrelated user files.
- Keep a successful PDF rename when later conversion fails, but publish no final Markdown or success manifest.
- Continue other papers after one paper fails. Return `partial_success` when at least one paper succeeds and at least one fails.
- Clean owned preflight and staging data after completion. Never delete unrelated files.

Runtime CLI phases:

```bash
python3 -B .agents/skills/convert-researchpaper-to-md/scripts/convert_researchpaper_to_md.py discover --url-path "<url_path>" --workspace-root "<workspace-root>"
python3 -B .agents/skills/convert-researchpaper-to-md/scripts/convert_researchpaper_to_md.py preflight-title --source "<local-downloaded-or-source-pdf>" --source-kind "<kind>" --workspace-root "<workspace-root>"
python3 -B .agents/skills/convert-researchpaper-to-md/scripts/convert_researchpaper_to_md.py prepare --preflight-json "<preflight.json>" --title-decision-json "<title-decision.json>" --workspace-root "<workspace-root>"
python3 -B .agents/skills/convert-researchpaper-to-md/scripts/convert_researchpaper_to_md.py publish --job-state "<job-state.json>" --language-decision-json "<language.json>" --audit-json "<audit.json>" --vie-markdown "<vie-draft.md>"
```

Omit `--vie-markdown` only for a confidently Vietnamese source.

## Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Host as Built-in AI Host
    participant Skill as Python Skill
    participant Docling
    participant FS as Workspace Filesystem

    User->>Host: url_path, optional force
    Host->>Skill: Discover and validate PDFs
    Skill->>Docling: Preflight pages 1-3
    Docling-->>Skill: BODY items and first-page render
    Skill-->>Host: Candidate title and evidence
    Host->>Host: Confirm first true paper heading
    alt Title confirmed
        Host->>Skill: Structured title decision
        Skill->>FS: Atomic PDF rename and hash verification
        Skill->>FS: Create matching title folder and staging
        Skill->>Docling: Standard OCR/layout/table/image conversion
        alt Text coverage insufficient
            Skill->>Docling: Tesseract full-page OCR retry
        end
        Docling-->>Skill: SUCCESS document, lossless structure, images
        Skill->>FS: Stage original.md, Asset, inventory, page renders
        Skill-->>Host: Language, translation, and audit tasks
        alt Source is Vietnamese
            Host->>Skill: vi decision and passing audit
        else Source is not Vietnamese
            Host->>Skill: Vietnamese Markdown and passing audit
        end
        Skill->>Skill: Completeness and structural parity gates
        Skill->>FS: Transactional publish; manifest last
        Skill-->>Host: Per-paper result
    else Title uncertain
        Skill-->>Host: review_required; no rename or title folder
    end
    Host-->>User: Batch result and output paths
```

## Error Handling & Fallbacks

| Error Code | Message | Fallback Behavior |
| --- | --- | --- |
| `INVALID_INPUT` | `url_path` is missing, relative, or unsupported. | Halt before conversion and request an absolute local path or valid URL. |
| `NO_PDFS_DISCOVERED` | No valid direct-child/same-origin PDFs were found. | Create no arbitrary output folders; ask for the correct path/page. |
| `UNSAFE_PATH` | A local path escapes the workspace or uses a symlink. | Reject it without mutation. |
| `REMOTE_HOST_BLOCKED` | URL targets credentials, localhost, or a private/local network. | Reject it; request a public URL or local workspace file. |
| `REMOTE_TOO_LARGE` | Remote input exceeds the configured limit. | Do not download further; request a smaller/local copy. |
| `INVALID_PDF` | File lacks a PDF signature or is unreadable. | Skip the paper and report its exact path/URL. |
| `PYTHON_VERSION_UNSUPPORTED` | Runtime is older than Python 3.10. | Use a Python 3.10+ runtime. |
| `DOCLING_MISSING` | Docling is not installed. | Install `docling>=2.117.0,<3` in the selected runtime. |
| `DOCLING_API_INCOMPATIBLE` | Installed Docling API does not match the reviewed 2.x flow. | Upgrade to a supported 2.x release and rerun tests. |
| `TITLE_NOT_FOUND` | Docling found no reliable BODY title/section heading. | Leave source unchanged and request manual review. |
| `TITLE_REVIEW_REQUIRED` | Built-in AI title confidence is below `0.85`. | Leave source unchanged; create no title folder. |
| `SOURCE_CHANGED` | PDF hash changed between phases. | Restart discovery and preflight. |
| `DUPLICATE_PDF` | Identical title/content already exists. | Report duplicate; never overwrite. |
| `SOURCE_RENAME_FAILED` | Atomic title rename failed. | Leave/create no title folder; report source and target. |
| `OUTPUT_PARENT_CREATE_FAILED` | Remote output parent could not be created after the incoming copy was title-renamed. | Keep the renamed incoming copy and report its exact location. |
| `REMOTE_PERSIST_FAILED` | Renamed remote copy could not be moved beside its output folder. | Keep/report the incoming renamed copy; create no paper folder. |
| `OUTPUT_FOLDER_CREATE_FAILED` | Folder creation failed after rename. | Keep successful renamed PDF and report the exact filesystem error. |
| `DOCLING_PREFLIGHT_FAILED` | Docling title preflight failed. | Skip without renaming. |
| `DOCLING_PARTIAL_SUCCESS` | Docling returned partial success. | Fail closed as review-required/error; publish nothing. |
| `DOCLING_CONVERSION_FAILED` | Full Docling conversion failed. | Keep renamed PDF, remove owned staging, and publish nothing. |
| `OCR_DEPENDENCY_MISSING` | Required Tesseract full-page OCR is unavailable. | Install Tesseract/language data and retry. |
| `DOCLING_OCR_FAILED` | Full-page OCR fallback failed. | Publish nothing and report Docling diagnostics. |
| `CONTENT_INCOMPLETE` | Page/text coverage remains insufficient. | Require review; never claim success. |
| `PAGE_RENDER_FAILED` | Docling did not retain a required page render. | Stop asset/completeness validation. |
| `ASSET_EXTRACTION_FAILED` | A Docling picture/table image could not be saved. | Publish nothing; report page and item label. |
| `ASSET_PARITY_FAILED` | A visual or image placeholder has no matching asset. | Re-extract or require review. |
| `LANGUAGE_REVIEW_REQUIRED` | Language confidence is insufficient. | Do not create or omit `vie.md` until confirmed. |
| `TRANSLATION_REQUIRED` | Non-Vietnamese paper lacks a Vietnamese draft. | Ask built-in AI to complete the translation. |
| `STRUCTURE_PARITY_FAILED` | Translation changed protected structure/information tokens. | Reject draft; regenerate only the failing translation. |
| `AI_AUDIT_FAILED` | Built-in AI reports unresolved omissions/additions. | Publish nothing until issues are resolved. |
| `PUBLICATION_FAILED` | Transactional final write failed. | Restore prior owned artifacts and retain no false success marker. |

## Known Bugs & Resolutions

> **Agent Rule (Error Handling & Bug Documentation):** In the future, when this skill encounters an error during input receiving, processing, or output generation, the AI agent must first propose a solution to the user. If the user agrees, the AI agent will fix the error. If the error is successfully fixed, the AI agent must update this section with the bug, cause, resolution, and regression test.

| Bug / Error | Cause | Resolution |
| --- | --- | --- |
| Test PDF fixture raised `ValueError: unsupported format character 'P'` | The fixture used Python `%` formatting on a string beginning with `%PDF-`, so `%P` was parsed as a format token. | Replaced `%` interpolation with f-strings and retained a literal `%PDF-` signature; all skill tests cover the fixture path. |
| Remote output parent could be created before the downloaded copy's title rename | The initial remote flow selected the final output target and created its missing parent inside the rename helper. | Title-rename the PDF atomically in workspace incoming storage first, then create the remote output parent, persist the renamed copy beside its future folder, and create the paper folder last; added an ordering regression test. |

## Performance Improvement Solutions

- [ ] Cache Docling model downloads in the selected Python runtime without storing models in final paper folders.
- [ ] Reuse one configured `DocumentConverter` per compatible batch when Docling guarantees safe converter reuse.
- [ ] Add bounded parallelism only after per-paper staging and AI context isolation remain deterministic.
- [ ] Stream long-paper translation by stable Docling block IDs with overlap, then reassemble and parity-check globally.
- [ ] Add real-Docling smoke fixtures for born-digital, scanned, mixed, multi-column, formula-heavy, and image-heavy papers in CI.
- [ ] Recheck the official Docling 2.x API and package version before dependency updates.
