# `ux-research-paper` Implementation Plan

## Objective

Create a workflow-owned two-stage research-paper pipeline at:

`.agents/workflows/ux-research-paper/`

The workflow owns these skills:

1. `convert-researchpaper-to-md` — Convert PDF input with Docling into a renamed PDF, complete source-language `original.md`, extracted `Asset/`, and a validated converter manifest. It no longer translates or creates `vie.md`.
2. `translate-to-vie` — After explicit user approval, analyze the author's complete voice and tone into Vietnamese `voice-tone.md`, then translate all eligible natural-language content into `vie.md` while preserving the Markdown structure and protected technical content.

Both skills use the host Built-in AI through file-based handoffs and never read `.env` or call an external LLM SDK.

The implementation follows `template/skill/SKILL.md`, `template/orchestrator/ORCHESTRATOR.md`, the live [Antigravity Projects documentation](https://antigravity.google/docs/projects), and the live [Antigravity Skills guide](https://antigravity.google/docs/skills), checked on 2026-08-02.

## Confirmed contract

- Public input is `url_path`: an absolute local/file PDF or directory, a direct public HTTP(S) PDF, or a public HTTP(S) collection page.
- The workflow processes exactly one paper per invocation. Zero candidates fail; multiple candidates require the user to provide one exact PDF URL/path.
- The converter always runs first.
- A successful converter output contains the renamed PDF, `original.md`, `Asset/`, and `.conversion-manifest.json`; it never contains `vie.md`.
- The orchestrator presents the converter output and pauses. Translation cannot run in the same stage or without a later explicit affirmative user response.
- Approval is bound to the exact `url_path`, renamed PDF path/hash, `original.md` path/hash, paper-folder path, and manifest hash.
- Any changed source, Markdown, manifest, path, or handoff field invalidates approval.
- `translate-to-vie` refuses to replace either `voice-tone.md` or `vie.md`; no `force` option exists.
- `voice-tone.md` is written in Vietnamese and contains actionable translation rules covering the complete paper.
- `vie.md` translates all eligible natural-language content without summarizing, omitting, adding, merging, splitting, or reordering it.
- Heading levels/order, block order/count, table dimensions and cell occupancy, image/link targets, code fences/content, formulas, citations, URLs, DOIs, bibliography entries, identifiers, numbers, units, and symbols remain protected.
- If the source is confidently Vietnamese, create `voice-tone.md` normally and copy `original.md` byte-for-byte to `vie.md` after integrity validation.

## Planned file tree

```text
.agents/workflows/ux-research-paper/
├── implementation_plan.md
├── ORCHESTRATOR.md
├── Analysis/
│   ├── analysis-convert-researchpaper-to-md.md
│   └── analysis-translate-to-vie.md
├── tests/
│   └── test_e2e_pipeline.py
└── skills/
    ├── convert-researchpaper-to-md/
    │   ├── SKILL.md
    │   ├── scripts/
    │   │   └── convert_researchpaper_to_md.py
    │   └── tests/
    │       ├── conftest.py
    │       ├── test_convert_researchpaper_to_md.py
    │       └── test_e2e_conversion.py
    └── translate-to-vie/
        ├── SKILL.md
        ├── scripts/
        │   └── translate_to_vie.py
        └── tests/
            ├── conftest.py
            ├── test_translate_to_vie.py
            └── test_e2e_translation.py
```

The current top-level `.agents/skills/convert-researchpaper-to-md/` is migrated into this workflow. The temporary top-level `.agents/skills/translate-to-vie/` planning folder is removed after this plan is preserved here.

## Converter changes

- Retain all PDF discovery, path/URL safety, title selection, title confidence, atomic rename, collision handling, Docling configuration, OCR fallback, page rendering, layout, table/image extraction, Markdown serialization, asset parity, content completeness, rollback, and cleanup behavior.
- Remove translation generation, `vie.md`, translation parity, and translation audit from `SKILL.md`, runtime APIs, CLI arguments, publication, result schema, and tests.
- Keep source-language classification for the translator handoff.
- Require a source-only audit of `original.md`, lossless Docling inventory, and assets.
- Publish `converter-manifest-v2` last with original public `url_path`, source identity, renamed PDF/paper-folder paths, `original.md`/asset paths, source and artifact hashes, source-language decision, Docling version/status, and conversion status.
- Expose a successful manifest/result as the sole translator handoff authority.
- Inspect a supplied prior handoff before discovery/Docling/AI, stream and hash remote PDFs, retry only transient network failures, enforce page/disk budgets, and synthesize bounded source-audit chunks.

## Translator design

Use one deterministic runtime, `scripts/translate_to_vie.py`, with importable helpers and these CLI phases:

```text
resolve            Validate one converter handoff and exact source identity.
create-approval    Bind an approval token to current source/original/manifest hashes.
prepare            Validate and consume approval, deny overwrite, parse stable blocks, and emit AI tasks.
build-voice-tone   Validate and render the Vietnamese voice profile, then create bounded translation chunks.
build-translation  Validate one resumable chunk at a time and reassemble only after global coverage.
publish            Validate the compact file-referenced audit and publish both files.
inspect-output     Revalidate existing translator outputs without modifying them.
```

The host Built-in AI supplies three structured JSON responses:

- `voice-tone-v1`: Vietnamese voice profile, translation rules, preferred terminology, protected-content rules, and all source block IDs.
- `translation-v1`: exactly one translated natural-language payload for every stable translatable source block in one bounded chunk.
- `translation-audit-v1`: `passed: true` with no issues only when the translation is complete and follows the voice profile.

Python owns Markdown parsing, stable block IDs, schema validation, block coverage/order, protected-token validation, deterministic reassembly, structural signatures, retry state, exclusive publication, rollback, and cleanup. AI never reconstructs arbitrary Markdown freely. Voice/audit tasks reference workspace files by path and SHA-256 instead of embedding complete documents.

For long papers, requests are chunked by stable block IDs and reassembled only when global coverage is exact.

## Approval state

Store an owned state under:

`.agents/scratch/ux-research-paper/<run-id>/approval.json`

Generate a SHA-256 approval token over a canonical `approval-v1` payload containing:

- `url_path`
- source PDF SHA-256
- `original.md` SHA-256
- manifest SHA-256
- renamed PDF path
- paper-folder path
- `original.md` path

The orchestrator presents the exact token with converter outputs and returns `awaiting_approval`. On a later affirmative response, recompute every field and require exact token equality before calling the translator. Approval is single-use but remains available to the same translation state across bounded retryable AI failures; it is removed after terminal invalidation, retry exhaustion, or successful publication.

## Atomic publication

- Recheck that neither `voice-tone.md` nor `vie.md` exists before AI processing and immediately before publication.
- Stage both outputs under the paper folder's owned `.translation-staging/<run-id>/` directory.
- Acquire an exclusive paper-folder lock.
- Create both final files exclusively.
- If the second creation fails, remove only the first file created by the current run.
- Preserve all unrelated and pre-existing user files.
- Remove owned staging and approval state on success; report exact owned paths if cleanup fails.

## Tests

### Converter

- Update all existing tests to source-only publication.
- Assert a successful run never creates `vie.md`.
- Validate `converter-manifest-v2`, all handoff paths/hashes, local renamed-PDF handoff, and remote handoff.
- Preserve existing title, Docling, OCR, asset, tamper detection, rollback, and cleanup tests.

### Translator

- Resolve exactly one paper; reject zero/multiple candidates.
- Validate local and remote converter handoffs.
- Reject invalid status/schema, source identity mismatch, path escape, missing artifacts, and hash changes.
- Validate approval token creation, exact matching, single use, and invalidation after changes.
- Deny existing `voice-tone.md` or `vie.md` before AI work and at publication.
- Validate Vietnamese voice-tone schema and complete source-block coverage.
- Reject missing, duplicate, reordered, merged, or split translations.
- Reject protected URL, DOI, citation, formula, number, unit, identifier, image, link, code, bibliography, table, heading, fence, or block-order changes.
- Copy an already Vietnamese source byte-for-byte.
- Publish nothing after AI audit failure; preserve unchanged approval and validated phases for bounded retry, then clean after exhaustion.
- Roll back the first output when the second output fails.
- Clean staging while preserving unrelated files.

### Workflow E2E

Create `tests/test_e2e_pipeline.py` that executes the full mocked pipeline:

1. Run converter and verify source-only output.
2. Create approval state and assert translation has not run.
3. Resume with an affirmative response and exact token.
4. Run translator and verify both outputs, structural parity, and protected tokens.
5. Verify approval/staging cleanup.
6. Cover changed-file approval invalidation, existing-output denial, and converter failure preventing translation.

## Execution and validation

1. Run `python3 .agents/scripts/check_libraries.py` before the workflow test run.
2. Initialize the new translator skill using the skill-creator initializer, then conform it to `template/skill/SKILL.md`.
3. Migrate and update the converter.
4. Create `ORCHESTRATOR.md`, translator runtime, and tests.
5. Run Python compile/CLI checks.
6. Run both skill test suites.
7. Run `.agents/workflows/ux-research-paper/tests/test_e2e_pipeline.py`.
8. Validate both skill definitions and inspect repository references for stale top-level paths or old `vie.md` assumptions.
9. Document any fixed bugs and regression tests in the relevant `SKILL.md`.
10. Stage, commit, and push all changes to `develop`.

## Post-analysis implementation status

The two Analyze Skill reports were generated sequentially on 2026-08-02. Every actionable recommendation scored below 8/10 has been implemented: early handoff skip, streamed/retried downloads, deterministic scratch cleanup, resource budgets, chunked source audit, file-referenced voice/audit tasks, resumable translation chunks, bounded AI retries, and expanded CommonMark/CRLF coverage. The skill checklists and orchestrator are the authoritative runtime contract.

## Approval

The user explicitly approved implementation and added this workflow-owned structure on 2026-08-02. Implementation may proceed under this updated contract.
