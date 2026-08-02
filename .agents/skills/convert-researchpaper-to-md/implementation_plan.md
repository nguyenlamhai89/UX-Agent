# `convert-researchpaper-to-md` Implementation Plan

## 1. Objective and confirmed contract

Create a standalone workspace skill at:

`.agents/skills/convert-researchpaper-to-md/`

The skill will:

- Accept one required string field, `url_path`, that may resolve to multiple research-paper PDF files.
- Use [Docling](https://github.com/docling-project/docling) as the primary PDF layout, OCR, table, picture, formula, structure, and Markdown conversion engine.
- Run a read-only Docling title preflight, rename each PDF to its first true research-paper heading, and make that rename the first filesystem mutation.
- Create a `<renamed-title>/` output folder only after the PDF rename succeeds.
- Write all per-PDF artifacts inside that folder.
- Always create `<renamed-title>/original.md` in the source language.
- Create `<renamed-title>/vie.md` only when the source paper is not already Vietnamese.
- Create `<renamed-title>/Asset/` and export every image/visual occurrence from the source PDF.
- Preserve the same heading hierarchy, section order, table structure, figure links, equations, citations, footnotes, references, and appendices in `original.md` and `vie.md`.
- Use the host's built-in AI only; no external AI API, API key, or `.env` access.
- Include deterministic Python helpers and Python tests.
- Fail closed: incomplete or ambiguous extraction must return `review_required` or `error`, never a false success.

The implementation will follow the workspace `template/skill/SKILL.md`, the live [Antigravity Projects documentation](https://antigravity.google/docs/projects), and the live [Antigravity Skills guide](https://antigravity.google/docs/skills). The current Skills guide places workspace skills under `.agents/skills/<skill-folder>/` and recommends focused skills, specific discovery descriptions, progressive disclosure, script-backed deterministic work, and explicit decision logic.

The Docling design is based on its current official [repository](https://github.com/docling-project/docling), [custom conversion](https://docling-project.github.io/docling/_generated/examples/custom_convert/), [figure export](https://docling-project.github.io/docling/_generated/examples/export_figures/), [table export](https://docling-project.github.io/docling/_generated/examples/export_tables/), and [full-page OCR](https://docling-project.github.io/docling/_generated/examples/full_page_ocr/) documentation.

## 2. Approval assumptions

The following operational details were not explicitly specified and are proposed for approval with this plan:

1. `url_path` supports:
   - A local directory path containing PDFs.
   - A `file://` directory URL containing PDFs.
   - A direct HTTP(S) PDF URL.
   - An HTTP(S) collection/directory page containing PDF links.
2. Local directories are scanned non-recursively. Remote collection pages are inspected once and are not recursively crawled.
3. For local/file sources, each `<renamed-title>/` folder is created beside its renamed source PDF.
4. For remote sources, each `<renamed-title>/` folder is created under:
   - `<workspace-root>/output/convert-researchpaper-to-md/`
5. Bibliography entries, citation keys, DOIs, URLs, formulas, numbers, and units remain verbatim in `vie.md`; natural-language body text, headings, captions, footnotes, and table cells are translated.
6. A hidden `.conversion-manifest.json` may be stored in each output folder for source hashes, structural signatures, validation results, and safe skip/rebuild decisions. The requested user-facing outputs remain `original.md`, conditional `vie.md`, and `Asset/`.
7. For a local/file source, the skill renames the actual source PDF in place without changing its contents. For an HTTP(S) source, a remote server file cannot be renamed, so only the downloaded workspace copy is renamed.
8. A successful source rename remains durable even if later conversion fails; the result and manifest retain the original filename, renamed path, title decision, and source hash so the operation is fully traceable.
9. Docling `2.117.0` is the currently reviewed implementation baseline and requires Python 3.10 or newer. The implementation phase will re-check the latest stable release before installing or pinning a compatible version.

Implementation will not begin until the user explicitly approves this plan and these assumptions.

## 3. Planned file tree

```text
.agents/skills/convert-researchpaper-to-md/
├── implementation_plan.md
├── SKILL.md
├── scripts/
│   └── convert_researchpaper_to_md.py
└── tests/
    ├── conftest.py
    ├── test_convert_researchpaper_to_md.py
    └── test_e2e_conversion.py
```

### `implementation_plan.md`

The approved implementation contract and execution checklist. This is the only file created during the planning phase.

### `SKILL.md`

Follow every applicable section and table in `template/skill/SKILL.md`:

- YAML frontmatter with only `name` and `description`.
- Description and trigger conditions.
- Exact Input contract and examples.
- Exact Output contract, response schema, file tree, and Markdown examples.
- API Key table specifying `None` and `Built-in AI`.
- Custom Instructions for Docling title preflight, source rename, folder creation, full Docling conversion, translation, validation, publication, and cleanup.
- Mermaid sequence diagram showing discovery, read-only title preflight, first filesystem mutation (rename), renamed-title folder creation, Docling conversion, built-in-AI translation/audit, validation, and batch results.
- Stable Error Handling & Fallbacks table.
- Known Bugs & Resolutions table and required regression-test policy.
- Performance Improvement Solutions checklist.

The description will make triggering specific: use this skill when converting one or more local or remote research-paper PDFs into complete, validated source-language Markdown with extracted assets and a structurally matched Vietnamese version.

### `scripts/convert_researchpaper_to_md.py`

One deterministic Python module with importable functions and CLI subcommands. It will own:

- Input normalization and source classification.
- Safe local/remote PDF discovery and download.
- Docling first-heading preflight, built-in-AI title validation, atomic source rename, and collision-safe output placement.
- Docling conversion status, PDF signature, encryption, page, text-layer, layout, and visual inspection.
- Docling page/picture rendering and `Asset/` extraction.
- Lossless `DoclingDocument` dictionary/JSON inventory generation.
- Built-in-AI task bundle generation and AI-response schema validation.
- Docling Markdown serialization and validated post-processing.
- Vietnamese structural-parity validation.
- Transactional publication, skip/force behavior, batch status, and cleanup.

The Python module will import Docling but will not import an external LLM SDK. It will expose a file-based built-in-AI boundary:

1. Docling produces the document hierarchy, lossless inventory, page/picture images, tables, formulas, and initial Markdown.
2. The skill's host agent validates the first title against the first-page render, translates only the natural-language fields in the Docling structure, and audits completeness.
3. Python validates AI responses against the unchanged Docling structure, renders/normalizes the final Markdown, and publishes only passing results.

This keeps runtime AI decoupled from the skill-creation AI and permits a future orchestrator to inject another model implementation without changing the extraction and validation core.

Suggested CLI phases:

```text
discover          Normalize url_path and list validated source PDFs.
preflight-title   Use Docling to find and validate the first true paper heading.
rename-source     Atomically rename the local PDF/downloaded copy to the safe title.
prepare           Create the renamed-title folder and run full Docling conversion.
validate-build    Validate AI block responses and build draft Markdown.
publish           Run all quality gates and transactionally publish final outputs.
inspect-output    Revalidate an existing output for skip/rebuild decisions.
```

Suggested importable entry point:

```python
convert_research_papers(
    url_path: str,
    *,
    force: bool = False,
    output_root: Path | None = None,
    ai_runner: Callable | None = None,
    http_client: object | None = None,
) -> dict
```

`output_root`, `ai_runner`, and `http_client` are test seams. The public skill input remains `url_path` with optional `force`.

### `tests/conftest.py`

Generate compact test PDFs inside pytest `tmp_path`; do not commit binary research papers. Fixtures will cover title and section-heading labels, multiline and non-ASCII titles, journal furniture, born-digital English, Vietnamese, scanned/image-only, mixed text/scans, multi-column layouts, tables, images, equations, footnotes, citations, bibliography, appendices, and colliding titles.

### `tests/test_convert_researchpaper_to_md.py`

Unit tests for discovery, path/URL safety, inspection, asset extraction, block schemas, structural signatures, translation parity, error mapping, publication, idempotency, and cleanup. Remote HTTP and built-in-AI responses will be mocked.

### `tests/test_e2e_conversion.py`

Per-skill end-to-end tests that execute the complete conversion pipeline with generated PDFs and a mocked built-in-AI runner. This is not a workflow-level E2E suite and will not modify any orchestrator.

## 4. Input contract

```json
{
  "url_path": "/absolute/path/to/research-papers",
  "force": false
}
```

Fields:

| Field | Type | Required | Behavior |
| --- | --- | --- | --- |
| `url_path` | `str` | Yes | Local directory, `file://` directory, direct HTTP(S) PDF, or HTTP(S) collection page. |
| `force` | `bool` | No | Rebuild valid prior outputs through staging; defaults to `false`. |

Local behavior:

- Require an absolute directory after resolving `file://`.
- Inspect direct children only.
- Match `.pdf` case-insensitively.
- Sort deterministically by normalized filename.
- Reject path traversal and symlink escapes outside the source directory.

Remote behavior:

- Permit only HTTP(S).
- Direct PDF URLs process one file.
- Collection pages discover PDF links once, resolve relative links, and use same-origin links by default.
- Canonicalize and deduplicate URLs.
- Validate MIME hints and require the `%PDF-` signature before parsing.
- Reject embedded credentials, unsupported schemes, private-network/localhost targets unless the runtime explicitly permits them, excessive redirects, oversized responses, and unsafe filenames.
- Apply explicit connection/read timeouts, redirect limits, link-count limits, download-size limits, and page-count limits.

If no valid PDF is discovered, halt before creating arbitrary output folders and return `NO_PDFS_DISCOVERED` with exact recovery instructions.

## 5. Output contract

For an English source originally named `paper-a.pdf` whose validated first heading is `Human-Centered Evaluation of AI Systems`, the parent directory becomes:

```text
<source-or-remote-output-parent>/
├── Human-Centered Evaluation of AI Systems.pdf
└── Human-Centered Evaluation of AI Systems/
    ├── original.md
    ├── vie.md
    ├── Asset/
    │   ├── page-001-image-001.png
    │   ├── page-003-figure-001.png
    │   └── page-005-visual-001.svg
    └── .conversion-manifest.json
```

For a Vietnamese source whose validated first heading is `Đánh giá trải nghiệm người dùng`, the parent directory becomes:

```text
<source-or-remote-output-parent>/
├── Đánh giá trải nghiệm người dùng.pdf
└── Đánh giá trải nghiệm người dùng/
    ├── original.md
    ├── Asset/
    └── .conversion-manifest.json
```

Rules:

- Derive both the renamed `.pdf` filename and output-folder name from the same validated, filesystem-safe first-heading title.
- Preserve readable Unicode and spaces in the renamed filename; preserve the `.pdf` extension.
- Create `Asset/` even when the PDF contains no images.
- Use UTF-8 for both Markdown files and JSON metadata.
- Preserve source-language content in `original.md`.
- Omit, rather than create an empty, `vie.md` for a confidently Vietnamese source.
- Use portable relative links such as `Asset/page-003-figure-001.png` in both Markdown versions.
- Do not publish intermediate inventories, page renders, OCR scratch data, or AI task bundles as final output.
- Successful PDFs remain published if another PDF in the same batch fails.

Top-level result shape:

```json
{
  "status": "success|partial_success|review_required|error",
  "url_path": "...",
  "source_type": "local_directory|file_directory|remote_pdf|remote_collection",
  "pdf_count": 2,
  "succeeded": 1,
  "skipped": 0,
  "review_required": 0,
  "failed": 1,
  "items": [
    {
      "source": "...",
      "original_source_filename": "paper-a.pdf",
      "renamed_source_filename": "Human-Centered Evaluation of AI Systems.pdf",
      "renamed_source_path": ".../Human-Centered Evaluation of AI Systems.pdf",
      "source_sha256": "...",
      "title_preflight": {
        "raw_heading": "Human-Centered Evaluation of AI Systems",
        "safe_title": "Human-Centered Evaluation of AI Systems",
        "docling_label": "title",
        "ai_validated": true,
        "confidence": 0.99,
        "collision_suffix": null,
        "rename_status": "renamed|already_named|remote_copy_renamed|failed"
      },
      "docling": {
        "version": "2.117.0",
        "document_schema_version": "...",
        "conversion_status": "success|partial_success|failure",
        "ocr_fallback": "none|hybrid|full_page",
        "errors": []
      },
      "output_dir": ".../Human-Centered Evaluation of AI Systems",
      "status": "success|skipped|review_required|error",
      "outputs": {
        "original": ".../original.md",
        "vie": ".../vie.md|null",
        "assets_dir": ".../Asset"
      },
      "language": "en",
      "translation_status": "created|not_required|failed",
      "validation": {
        "passed": true,
        "checks": {},
        "warnings": []
      },
      "error_code": null,
      "message": "...",
      "staging_cleaned": true
    }
  ]
}
```

## 6. Per-PDF processing sequence

### 6.1 Discover and validate the source

1. Normalize `url_path` and classify its source type.
2. Discover candidate PDFs without recursive crawling.
3. Validate local files as readable regular files or validate remote content using response limits, MIME hints, and PDF signature.
4. Compute SHA-256 for content identity and duplicate detection.
5. Reject inaccessible, malformed, unsupported, or encrypted PDFs with stable per-item errors.
6. Do not create an output folder or rename anything during discovery.

### 6.2 Preflight the first heading and rename the PDF

The title preflight is read-only and exists solely because the source cannot be renamed correctly without first reading its heading. Renaming is the first mutating action and occurs before full-document conversion.

1. For a remote source, download the validated PDF into a workspace-owned incoming area while retaining its source URL and original download name. Do not create the final output folder yet.
2. Run a limited Docling preflight over the first content page, starting with page 1 and expanding through front matter only when no body heading is available.
3. Iterate the `DoclingDocument` in body reading order and select:
   - The first non-empty BODY item labeled `DocItemLabel.TITLE`.
   - Otherwise, the first non-empty BODY item labeled `DocItemLabel.SECTION_HEADER` on the first content page.
4. Exclude `PAGE_HEADER`, `PAGE_FOOTER`, furniture-layer items, journal mastheads, running titles, DOI banners, issue metadata, and other material that is not the research-paper heading.
5. Join a multiline title in reading order with single spaces; preserve its complete text rather than shortening or paraphrasing it.
6. Ask built-in AI to validate the Docling title candidate against the first-content-page render. Require the candidate to be the actual paper heading, not an author, affiliation, abstract label, journal name, or running header.
7. If Docling and visual validation disagree, no title exists, or confidence is below the documented threshold, return `TITLE_REVIEW_REQUIRED`. Leave the source filename unchanged, do not create the output folder, and provide the candidate evidence to the user.
8. Convert the approved title to a safe filesystem name:
   - Normalize Unicode to NFC.
   - Collapse line breaks and repeated whitespace while preserving readable spaces.
   - Remove NUL/control characters and replace path separators/filename-forbidden characters with safe separators.
   - Trim trailing spaces/dots, reject `.`/`..`, and protect operating-system reserved names.
   - Preserve non-ASCII characters, including Vietnamese.
   - Enforce a maximum basename length while preserving enough title text and the `.pdf` extension.
9. Resolve collisions without overwriting:
   - If the target path is the same file, report `already_named` and do not rename again.
   - If a different file already uses the title, append a deterministic short source-hash suffix to both the PDF stem and output-folder stem.
   - If files have identical content hashes, report the duplicate explicitly rather than overwriting either source.
10. Rename atomically on the same filesystem:
    - Local/file input: rename the actual source PDF.
    - HTTP(S) input: rename only the downloaded workspace copy because the remote server object cannot be mutated, and keep that renamed copy beside its output folder under the remote output root.
11. Record original path/name, renamed path/name, raw heading, safe title, Docling label/provenance, AI validation/confidence, source SHA-256, collision suffix, and rename status.
12. The successful rename remains durable if later conversion fails. A rename failure halts that item before folder creation or full conversion.

### 6.3 Create the required renamed-title folder

1. Derive the folder stem from the successfully renamed PDF stem, including any deterministic collision suffix.
2. Create `<renamed-title>/` beside the local renamed PDF or beside the persisted renamed downloaded copy under the remote output root.
3. Create `<renamed-title>/.staging/<run-id>/` for all incomplete work.
4. Re-runs use the source hash and prior manifest to recognize an already-renamed PDF and avoid rename loops.
5. Never write apparently valid `original.md`, `vie.md`, or `Asset/` until their publication transaction is ready.

### 6.4 Run full Docling conversion

Docling is the main converter. Configure its Python API with:

- `DocumentConverter` with a PDF `PdfFormatOption`.
- `PdfPipelineOptions(do_ocr=True, do_table_structure=True)`.
- `TableStructureOptions(do_cell_matching=True)`.
- `generate_page_images=True` and `generate_picture_images=True`.
- A tested `images_scale` (initially `2.0`) for readable page and element renders.
- Automatic accelerator selection with bounded worker/thread settings.

For scanned or unreliable text layers:

1. Run Docling's standard hybrid OCR first.
2. If quality gates show missing page text, retry through Docling's documented full-page OCR mode.
3. Use a supported Docling OCR backend; Tesseract `lang=["auto"]` is the planned multilingual fallback when its executable and trained language data are available.
4. If OCR dependencies/models are unavailable, return a dependency/model error rather than using an unapproved remote service.

Handle Docling conversion status explicitly:

- `SUCCESS`: continue to validation.
- `PARTIAL_SUCCESS`: default to `review_required`; proceed only if every reported error is proven non-content and every page/content gate passes.
- Failure: halt the item and preserve structured diagnostics.

Use Docling for layout, reading order, OCR, table structure, pictures/charts, formulas/code, captions, footnotes, references, body/furniture separation, page images, element images, and initial Markdown. Export a lossless `DoclingDocument` dictionary/JSON representation into staging before Markdown post-processing.

Other PDF tools may independently validate page count, rendering, or missed visual occurrences and provide narrow extraction fallbacks, but they must not replace Docling as the primary converter.

Record from Docling:

- Page number, size, rotation, and render path.
- Typed content labels, body-tree reading order, furniture separation, provenance, and bounding boxes.
- Text-layer/OCR evidence, character/word counts, and confidence warnings.
- Section hierarchy and title/heading levels when available.
- Table data, cells, row/column spans, and cell-matching evidence.
- Pictures, charts, captions, page images, and picture images.
- Formulas and code items.
- Footnotes/endnotes.
- Page headers/footers and their content layers.
- Citations and references.
- Appendix and supplementary-section boundaries.
- Intentional blank-page evidence.

Classify each paper as born-digital, scanned, mixed, multi-column, or inaccessible. Docling Markdown alone is not proof of completeness; its lossless document representation, statuses, errors, provenance, page renders, and independent validators remain required.

### 6.5 Extract and validate `Asset/`

For every image/visual occurrence:

1. Use Docling `PictureItem.get_image(document)` for each detected picture/chart and `TableItem.get_image(document)` for visual table companions after enabling page and picture image generation.
2. Use Docling provenance and page images to crop an item when direct element extraction is unavailable or visually inadequate.
3. Preserve a reliable original/vector visual when Docling exposes it; otherwise use the Docling-rendered high-resolution PNG.
4. Use Docling's referenced-image serialization mode so Markdown points to files under `Asset/` instead of embedded base64 data or generic placeholders.
5. Name assets by page and occurrence, not by untrusted source strings.
6. Preserve repeated occurrences rather than silently deduplicating them; the manifest may note identical hashes.
7. Store Docling self-reference, source page, bounding box, type, hash, and caption association in the staging inventory.
8. Link meaningful figures/charts/logos at their correct position in Markdown. Keep non-content decorative images discovered by independent visual validation in `Asset/` and inventory them even if they are not inserted into prose.

Quality gates:

- Every detected image/visual occurrence maps to an asset file or an explicit unresolved error.
- Every Markdown asset link resolves inside `Asset/`.
- No path escapes `Asset/`.
- Asset count, order, figure labels, captions, and links are identical in `original.md` and `vie.md`.

### 6.6 Use the lossless `DoclingDocument` as the canonical inventory

Export `conversion_result.document.export_to_dict()` to staged lossless JSON and treat Docling self-references, body order, typed labels, tables, pictures, formulas, provenance, and content layers as the structural source of truth. Normalize it into the following validation view without discarding Docling fields:

```text
document
  page
    block: heading | paragraph | list | table | figure | equation |
           footnote | citation | reference | header | footer | appendix
```

Every block records its Docling self-reference, source page, bounding box/provenance, original text, ordering, content layer, label, and structural metadata. Tables record row/column counts, header cells, occupancy, and merged-cell spans. Figures record Docling picture references, asset IDs, and captions. Equations, citations, references, and footnotes retain stable identifiers.

The lossless Docling inventory—not free-form AI prose—is the structural source of truth used to render both Markdown versions.

### 6.7 Use built-in AI for title validation, translation, and audit

The host agent will process one paper at a time to avoid context leakage. For long papers, it will use page/section chunks with overlap and stable block IDs.

Docling, not built-in AI, owns the initial document reconstruction. Built-in AI may:

- Validate the preflight paper title against its page render.
- Confirm the source language.
- Translate only declared natural-language fields while retaining all Docling self-references and structure.
- Conduct a second completeness audit against page renders and deterministic inventories.
- Flag possible Docling omissions or misclassifications for review; it must not silently rebuild or reorder the Docling structure.

The AI instructions will require:

- Never invent, summarize, simplify, or silently omit content.
- Preserve uncertainty as an explicit issue tied to a Docling self-reference or page region.
- Return only the declared structured schema with original Docling self-references.
- Preserve all numbers, units, symbols, equations, identifiers, URLs, DOIs, citation keys, table dimensions, figure numbers, and page provenance.
- Keep separate papers isolated.

If the built-in AI is unavailable, malformed, or cannot resolve low-confidence content, the item becomes `review_required` or `error`; the skill will not fall back to an external model.

### 6.8 Render `original.md`

Start from Docling's Markdown serializer (`save_as_markdown`/`export_to_markdown`) with referenced images, then deterministically normalize paths and complex structures against the validated lossless `DoclingDocument`:

- Preserve the original language and document order.
- Preserve title, authors, affiliations, abstract, keywords, every body section, acknowledgments, declarations, references, and appendices.
- Preserve meaningful headers/footers and page numbers; exclude only verified repetitive non-content furniture.
- Use Markdown headings with the reconstructed hierarchy.
- Use Markdown tables when rectangular fidelity is possible.
- Use HTML tables when row/column spans or complex formatting cannot be represented faithfully in basic Markdown.
- Use a table image only as a visual companion, never as a substitute for recoverable textual table data.
- Use LaTeX delimiters for faithfully recovered equations; pair with a rendered equation asset when symbol fidelity is uncertain.
- Preserve citations and bibliography ordering.
- Use Markdown footnotes or a deterministic equivalent.
- Add page provenance comments only where required to make ambiguous page/order coverage auditable.

No output may contain unresolved placeholders such as `TODO`, `[missing]`, hallucinated text, or silently truncated final sections.

### 6.9 Detect Vietnamese and conditionally translate

1. Perform deterministic language evidence checks over title, abstract, and samples across the full paper.
2. Ask built-in AI to confirm the predominant language with confidence and cited block IDs.
3. If both checks confidently identify Vietnamese, set `translation_status: not_required` and omit `vie.md`.
4. If the source is not predominantly Vietnamese, translate the validated canonical block tree into Vietnamese.
5. If language checks conflict or remain low confidence, return `review_required` rather than guessing whether to omit `vie.md`.

Translation rules:

- Translate natural-language headings, paragraphs, lists, captions, footnotes, and table cells.
- Preserve the exact block tree, heading levels, section order, table row/column/span signatures, figure/asset links, equation content, citation markers, footnote IDs, reference ordering, appendix structure, URLs, DOIs, identifiers, numbers, and units.
- Preserve bibliography entries verbatim for citation integrity.
- Preserve existing Vietnamese text and proper Unicode; never transliterate Vietnamese.
- Generate translation from the validated canonical original, never independently from raw PDF text.

### 6.10 Validate completeness and structural parity

A result may be published only if every mandatory gate passes.

Title and rename:

- Confirm the renamed PDF stem and output-folder stem match the validated safe first heading, including any required collision suffix.
- Confirm the source content SHA-256 did not change during rename.
- Confirm local and remote-copy rename semantics match the source type.
- Confirm no output folder was created before rename success.

Docling conversion:

- Record and validate Docling package version, `DoclingDocument` schema version, pipeline options, model/OCR backend versions, conversion status, and reported errors.
- Reject unsupported schema/API versions.
- Treat `PARTIAL_SUCCESS` as `review_required` unless every reported issue is proven non-content and every other mandatory gate passes.
- Reconcile initial Docling Markdown with the lossless Docling body tree rather than assuming serialization alone is complete.

Page coverage:

- Every PDF page is represented by content, assets, a verified intentional blank state, or a terminal inaccessible-page error.
- No page is silently skipped.

Content inventory:

- Reconcile Docling body/furniture items, typed labels, section, block, table, picture, caption, formula, footnote, citation, reference, appendix, and meaningful metadata counts.
- Compare page-level character/word evidence with reconstructed text and explain any material discrepancy.
- Reject empty, near-empty, truncated, abruptly ended, or placeholder-bearing output.

Heading and ordering:

- Validate heading sequence, nesting, and no unexplained hierarchy jumps.
- Validate source section order.

Tables:

- Compare ordinal, label/caption, row count, column count, cell occupancy, merged spans, header pattern, and order.

Assets:

- Compare detected visual occurrences, extracted files, hashes, links, labels, captions, and ordering.

Equations:

- Compare equation count, order, identifiers, and normalized formula content.

Citations and references:

- Compare citation-marker sequence, citation keys, reference count/order, DOI values, and URLs.

Original/Vietnamese parity:

- Compare canonical block-type sequence.
- Compare heading levels and count.
- Compare table signatures.
- Compare figure/asset references.
- Compare equations.
- Compare citation and footnote identifiers.
- Compare reference and appendix ordering.
- Permit differences only in approved natural-language fields.

Built-in-AI completeness audit:

- Run a second pass against page renders and the final normalized Docling inventory.
- Require every reported omission or uncertainty to be resolved or surfaced as a failed gate.

Any unresolved mismatch becomes `review_required` or a stable validation error, never `success`.

### 6.11 Publish transactionally

1. Keep all drafts, inventories, renders, and candidate assets in `.staging/<run-id>/`.
2. Validate the complete publication set before touching current final outputs.
3. Back up existing skill-owned final artifacts inside the output folder.
4. Replace `Asset/`, `original.md`, conditional `vie.md`, and `.conversion-manifest.json` using `os.replace`/directory renames where possible. The source PDF has already been renamed and is not part of this publication transaction.
5. Write the successful manifest/commit marker last. Consumers treat an output as valid only when the manifest hashes match every required artifact.
6. Roll back from the backup if any publication step fails.
7. Remove a stale prior `vie.md` only when a successful forced rebuild proves the new source is Vietnamese.
8. Preserve unrelated user files in the output folder.
9. Clean staging and backups after success; clean failed staging after recording the structured error.

The pre-created `<renamed-title>/` directory may remain empty after a failed full conversion, but it must never contain a success manifest or apparently complete Markdown set.

## 7. Idempotency, skip, and batch behavior

Default behavior:

- Compute/obtain the source fingerprint.
- Look up the fingerprint in valid manifests so a PDF already renamed to its title is reported `already_named` instead of receiving another suffix or rename loop.
- If `.conversion-manifest.json` matches the source hash, skill version, final hashes, language decision, and all validators still pass, return `skipped`.
- If output is missing, stale, invalid, or incomplete, rebuild through staging.
- Remote sources may use conditional requests (`ETag`/`Last-Modified`) but must verify content when the server cannot prove it is unchanged.

`force: true`:

- Rebuild in staging.
- Preserve the previous valid output until the replacement passes every gate.
- If rebuilding fails, keep the previous valid output and return the new failure status.

Batch behavior:

- Process each PDF in an isolated staging directory.
- Continue after independent per-PDF errors.
- Return `success` when every item succeeds or validly skips.
- Return `partial_success` when at least one item succeeds/skips and another fails or requires review.
- Return `review_required` when no item fails but at least one cannot pass completeness/parity gates.
- Return `error` when no item succeeds/skips and at least one terminal error occurs.

## 8. Error codes and fallbacks

`SKILL.md` will document stable codes including:

| Error code | Meaning | Fallback |
| --- | --- | --- |
| `INVALID_URL_PATH` | Missing, empty, or malformed input. | Halt and instruct the user to provide a supported path/URL. |
| `UNSUPPORTED_SCHEME` | Scheme is not local, `file`, HTTP, or HTTPS. | Halt; never reinterpret it. |
| `SOURCE_NOT_FOUND` | Local source does not exist. | Halt with exact expected path type. |
| `NO_PDFS_DISCOVERED` | Source contains no valid PDFs. | Halt and list accepted `.pdf` placement rules. |
| `TITLE_NOT_FOUND` | Docling found no body title/section heading in the preflight range. | Leave the filename unchanged and request review. |
| `TITLE_REVIEW_REQUIRED` | Docling and built-in visual validation disagree or confidence is low. | Leave the filename unchanged; do not create the output folder. |
| `TITLE_INVALID_FILENAME` | The title cannot produce a safe non-empty filename. | Leave the source unchanged and report sanitization evidence. |
| `PDF_NAME_COLLISION` | Another PDF already uses the safe title. | Append a deterministic short source-hash suffix; never overwrite. |
| `PDF_RENAME_FAILED` | Atomic local/download-copy rename failed. | Halt before folder creation and full conversion. |
| `OUTPUT_FOLDER_CREATE_FAILED` | The renamed-title folder could not be created. | Preserve the successful rename and return an actionable filesystem error. |
| `UNSAFE_PATH` | Traversal, symlink escape, or unsafe filename. | Reject that source/item. |
| `REMOTE_FETCH_FAILED` | Remote request failed. | Retry only transient failures with a bounded policy. |
| `REMOTE_TIMEOUT` | Network deadline exceeded. | One bounded retry, then per-item error. |
| `REMOTE_REDIRECT_LIMIT` | Too many redirects. | Reject the URL. |
| `REMOTE_SIZE_LIMIT` | Page or PDF exceeds configured size. | Reject before unbounded download. |
| `REMOTE_CROSS_ORIGIN_LINK` | Collection link violates same-origin policy. | Ignore and report it; do not follow. |
| `REMOTE_NOT_PDF` | MIME/signature validation fails. | Reject the item. |
| `DOCLING_NOT_INSTALLED` | A compatible Docling package is unavailable. | Halt before preflight and report the required Python/package version. |
| `DOCLING_VERSION_UNSUPPORTED` | Installed Docling API is outside the tested compatibility range. | Halt and provide an install/upgrade suggestion. |
| `DOCLING_MODEL_UNAVAILABLE` | Required Docling layout/OCR model or language data is unavailable. | Do not call an external service; request dependency/model setup. |
| `DOCLING_SCHEMA_UNSUPPORTED` | Lossless `DoclingDocument` schema cannot be validated. | Do not publish; update the adapter and tests first. |
| `DOCLING_PARTIAL_SUCCESS` | Docling reports partial conversion. | Return `review_required` unless every reported issue is proven non-content and all gates pass. |
| `DOCLING_CONVERSION_FAILED` | Docling cannot convert the PDF. | Preserve diagnostics and fail the item. |
| `PDF_PARSE_FAILED` | PDF is malformed or unreadable. | Confirm with an independent validator, then fail. |
| `PDF_ENCRYPTED` | Password is required. | Halt that item and request an unlocked PDF. |
| `AI_UNAVAILABLE` | Built-in AI cannot run. | Do not use an external provider or publish drafts. |
| `AI_MALFORMED_RESPONSE` | AI output violates the canonical schema. | Retry once with validation feedback, then fail/review. |
| `OCR_INCOMPLETE` | Scanned content remains unreadable. | Return `review_required`; do not omit the region. |
| `EXTRACTION_INCOMPLETE` | Deterministic inventory cannot account for content. | Return `review_required`. |
| `CONTENT_COVERAGE_FAILED` | Page/block completeness gate fails. | Do not publish. |
| `STRUCTURE_MISMATCH` | Heading or block sequence differs. | Retry translation once, then fail parity. |
| `TABLE_PARITY_FAILED` | Table signatures differ. | Do not publish `vie.md`. |
| `ASSET_PARITY_FAILED` | Visual inventory/files/links differ. | Re-extract or return review-required. |
| `EQUATION_PARITY_FAILED` | Formula inventory/content differs. | Do not publish. |
| `CITATION_PARITY_FAILED` | Citation/reference integrity differs. | Do not publish. |
| `TRANSLATION_FAILED` | Vietnamese conversion fails. | Preserve staging diagnostics; do not publish incomplete set. |
| `PUBLICATION_FAILED` | Transactional final write fails. | Roll back to prior valid output. |
| `CLEANUP_FAILED` | Temporary data could not be removed. | Report the exact path without deleting unrelated files. |

Fallback order for recoverable PDF content is:

1. Docling standard PDF pipeline with hybrid OCR and table structure.
2. Docling documented full-page OCR with a compatible local OCR backend; use Tesseract `lang=["auto"]` when available.
3. Docling page/picture/table image rendering and provenance-based visual fallback.
4. Independent local page-count/render/visual validation without replacing Docling's structure.
5. Built-in-AI completeness audit tied to Docling self-references and page regions.
6. `review_required` when completeness remains uncertain.

## 9. Security and preservation controls

- Do not read or create `.env`.
- Do not accept or persist API keys.
- Do not write outside the workspace for remote outputs or outside the local source directory for local outputs.
- Keep remote pre-rename downloads inside a workspace-owned incoming directory; after a successful title rename, persist the renamed copy beside its output folder and never treat it as temporary. Keep all remaining temporary files inside each output folder's `.staging/` directory.
- Never alter PDF contents. Rename a local source PDF only after title validation and rename a remote source only as a downloaded workspace copy.
- Never overwrite a colliding PDF during title-based rename; use atomic same-filesystem rename and deterministic collision suffixes.
- Never delete unrelated files in an output directory.
- Bound network requests, downloads, discovered links, page counts, render dimensions, and extracted asset sizes.
- Reject traversal, control characters, unsafe schemes, remote embedded credentials, and symlink escapes.
- Use exact resolved-path containment checks before every write/delete.
- Redact credentials/query secrets from logs and result messages.
- Use deterministic filenames and SHA-256 hashes for provenance and collision checks.
- Record the old/new source paths and verify the content hash is unchanged after every rename.

## 10. Testing plan

### Test fixtures

Generate all PDFs at test time with small deterministic fixtures. Where practical, use ReportLab plus Pillow; create scanned fixtures by rendering known text into an image before embedding it in a PDF.

### Unit coverage

- Empty/invalid `url_path`.
- Local and `file://` directory discovery.
- Direct remote PDF and remote collection discovery.
- Same-origin policy, redirects, timeouts, size limits, MIME/signature combinations, URL deduplication, and mocked HTTP errors.
- Non-recursive discovery.
- Unsafe path, symlink escape, filename sanitization, Unicode names, duplicate stems, and content-hash duplicates.
- First BODY `TITLE` selection and first BODY `SECTION_HEADER` fallback.
- Multiline title joining, non-ASCII/Vietnamese title preservation, filename-forbidden characters, reserved names, and maximum length.
- Page-header/footer, journal furniture, DOI banner, author, affiliation, and abstract-label exclusion from title selection.
- Built-in-AI title validation, low-confidence/ambiguous title review, and no mutation on title failure.
- Atomic local source rename, remote downloaded-copy rename, unchanged content hash, collision suffix, duplicate-title handling, and rename failure.
- Folder creation only after successful rename, durable rename on later conversion failure, and no output folder on title/rename failure.
- Already-renamed reruns and manifest-based prevention of rename loops.
- Docling dependency/version/schema/model checks and conversion status mapping.
- Docling `SUCCESS`, `PARTIAL_SUCCESS`, and failure handling.
- Born-digital, scanned, mixed, multi-column, encrypted, malformed, and blank-page inspection.
- Docling hybrid OCR and mocked full-page OCR fallback.
- Docling picture/table export, referenced-image paths, rendered fallback, duplicate visual occurrences, captions, and missing assets.
- Lossless `DoclingDocument` schema, body/furniture order, typed labels, provenance, and normalized validation-view checks.
- Heading hierarchy and block-order signatures.
- Markdown and complex HTML table rendering.
- Table row/column/span parity.
- Equation, citation, reference, footnote, figure, appendix, and asset parity.
- Vietnamese source detection and `vie.md` omission.
- Conflicting/low-confidence language detection returning `review_required`.
- Translation Unicode and invariant-token preservation.
- Empty, truncated, placeholder-bearing, and incomplete AI output rejection.
- Transactional publication, rollback, stale `vie.md` removal after valid rebuild, and manifest-last semantics.
- Skip, stale-manifest rebuild, `force`, and preservation of prior valid output.
- Staging cleanup and unrelated-file/source-PDF preservation.
- Stable error/result dictionaries.

### Per-skill E2E coverage

1. Batch with one English paper and one Vietnamese paper:
   - Each source PDF is renamed from its initial arbitrary filename to its validated first-heading title before its output folder is created.
   - English folder has `original.md`, `vie.md`, `Asset/`, and manifest.
   - Vietnamese folder has `original.md`, `Asset/`, and manifest but no `vie.md`.
2. English paper with headings, table, figure, equation, footnote, citations, references, and appendix:
   - Both Markdown files pass exact structural signatures.
   - Every asset link resolves.
3. Scanned/mixed paper with mocked built-in vision:
   - All page blocks are accounted for.
4. Partial-success batch:
   - A malformed/encrypted PDF fails without removing successful outputs.
5. Forced rebuild failure:
   - Prior valid output remains intact.
6. Repeat execution:
   - Already-renamed PDFs are not renamed again and valid unchanged outputs return `skipped`.

The built-in-AI boundary will be mocked with realistic structured responses. Tests will validate prompts/task bundles and response schemas without making nondeterministic model calls.

## 11. Dependency and validation commands after approval

At implementation/runtime start, run the workspace dependency check and report warnings without halting unless an immediately required dependency is missing:

```bash
python3 .agents/scripts/check_libraries.py
```

Prefer the bundled runtime and existing PDF libraries. Do not install dependencies during planning. During implementation, add or install only a missing critical dependency after reporting it and obtaining any required approval.

Docling requirements:

- Python 3.10 or newer.
- Docling `2.117.0` is the currently reviewed baseline; re-check the latest stable [Docling release](https://pypi.org/project/docling/) at implementation time and record the installed/tested version.
- Use the standard local Docling PDF pipeline; do not configure a remote VLM or remote conversion service.
- Verify required Docling layout/table models are available before processing.
- Verify the selected OCR backend and language data before scanned-paper processing. Tesseract `lang=["auto"]` requires its executable and compatible trained data.
- Do not auto-upgrade Docling during ordinary skill runtime. Report missing/outdated/incompatible versions and provide an explicit installation/upgrade command.

Run skill tests:

```bash
python3 -m pytest -q .agents/skills/convert-researchpaper-to-md/tests
```

Run the focused per-skill E2E test:

```bash
python3 -m pytest -q .agents/skills/convert-researchpaper-to-md/tests/test_e2e_conversion.py
```

Validate the skill scaffold/frontmatter with the skill-creator validator and inspect conformance against the workspace template:

```bash
python3 /Users/hai.nl01/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/skills/convert-researchpaper-to-md
```

```bash
sed -n '1,240p' template/skill/SKILL.md
sed -n '1,320p' .agents/skills/convert-researchpaper-to-md/SKILL.md
find .agents/skills/convert-researchpaper-to-md -maxdepth 3 -type f -print
```

Manual smoke test:

1. Use a local directory with one English and one Vietnamese research paper.
2. Give both PDFs arbitrary initial filenames and verify Docling identifies each first true body heading.
3. Verify each local PDF is renamed to its safe title before its same-stem output folder is created.
4. Verify output placement, conditional `vie.md`, complete Docling-referenced assets, UTF-8, headings, tables, equations, citations, references, and page coverage.
5. Re-run and verify no rename loop and `skipped`.
6. Re-run with `force: true` and verify transactional output replacement without another source rename.
7. Test a remote collection URL and confirm only the downloaded copy is renamed, with remote output placement and same-origin filtering.

## 12. Implementation sequence after approval

1. Run the skill-creator initialization script for `convert-researchpaper-to-md` targeting `.agents/skills/` with a `scripts/` resource, then reconcile the generated scaffold to the stricter workspace `template/skill/SKILL.md`. Remove any generated Codex-only metadata not allowed by the workspace template.
2. Create `tests/` and the planned Python files.
3. Re-check current Docling/Python requirements and implement local/file/remote discovery, validation, security limits, and hashing.
4. Implement the read-only Docling title preflight, first BODY heading selection, built-in visual validation, safe title normalization, atomic local/download-copy rename, collision handling, and already-renamed detection.
5. Implement output-folder creation strictly after rename success, per-PDF staging, manifests, publication markers, rollback, skip/force, and cleanup.
6. Implement full Docling conversion with OCR, table structure, page/picture images, lossless JSON, conversion-status handling, and `Asset/` export/fallbacks.
7. Implement the schema-constrained built-in-AI translation/audit handoff documented in `SKILL.md` without allowing AI to replace Docling's structure.
8. Implement Docling Markdown serialization and deterministic normalization for `original.md`.
9. Implement language confirmation, conditional translation, and invariant preservation.
10. Implement all title/rename, Docling compatibility, completeness, and structural-parity validators.
11. Implement structured batch results and stable error mapping.
12. Add unit and per-skill E2E tests.
13. Run dependency checks, validation, all skill tests, and the manual smoke test.
14. If any bug is found and fixed, document the bug/cause/resolution in `SKILL.md` and add a regression test.

## 13. Files explicitly not created or modified by this implementation

- No orchestrator or `.agents/workflows/` file.
- No workflow `tests/test_e2e_pipeline.py`.
- No `.env` file.
- No external API-key configuration.
- No external LLM SDK configuration.
- No source PDF content is modified; only local filenames are intentionally renamed to the validated first heading as required.
- No unrelated existing skill.
- No global skill under the user home directory.
- No project code or temporary artifact outside the workspace.

## 14. Approval gate

This planning phase creates only `implementation_plan.md`. Creating `SKILL.md`, scripts, tests, dependencies, or runtime outputs must wait for an explicit user response approving this plan and its assumptions.
