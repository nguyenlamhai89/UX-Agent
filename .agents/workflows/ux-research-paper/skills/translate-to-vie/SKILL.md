---
name: translate-to-vie
description: Analyze the complete author voice and tone of one approved converted research paper, write Vietnamese voice-tone.md instructions, and translate original.md fully into structurally identical vie.md. Use only as the second stage of ux-research-paper after converter success and explicit hash-bound user approval.
---

# Translate to Vietnamese

## Description

Translate exactly one successful `convert-researchpaper-to-md` output into Vietnamese. First analyze every source Markdown block to define the author's voice, tone, terminology, certainty, sentence rhythm, disciplinary register, and evidence style. Write actionable instructions in Vietnamese to `voice-tone.md`. Then use those instructions to translate every eligible natural-language block in `original.md` and publish `vie.md` without changing protected Markdown or technical content.

Run only after the `ux-research-paper` orchestrator presents the converter output and receives a later affirmative user response containing the exact approval token. Approval is bound to the source PDF, `original.md`, manifest, and paths; any change invalidates it.

Use `scripts/translate_to_vie.py` as the deterministic runtime. The host Built-in AI supplies structured voice, translation, and audit responses. No external AI API or SDK is used.

## Input

- **Type**: `dict`
- **Format**:

  | Field | Type | Required | Rules |
  | --- | --- | --- | --- |
  | `url_path` | `str` | Yes | The exact original public PDF URL/path supplied to the converter. |
  | `converter_handoff` | `dict` or absolute JSON path | Yes, orchestrator-provided | Exactly one successful `converter-manifest-v2` result. |
  | `approval_state` | absolute JSON path | Yes, after conversion | Workspace-owned hash-bound state created by the orchestrator/runtime. |
  | `approval_response` | `str` | Yes, on resume | Must be affirmative and contain the exact current approval token. |
  | `translation_budget` | `dict` | No | Positive limits for source characters/estimated tokens, block count, blocks/chars/estimated tokens per chunk, chunk count, and AI attempts; defaults are fail-closed and configurable. |

- **Location**: `request_body`
- **Input File(s)**:
  - `<paper-folder>/original.md` — Complete source-language Markdown produced by `convert-researchpaper-to-md`.
  - `<paper-folder>/.conversion-manifest.json` — Authoritative `converter-manifest-v2` handoff.
  - `<paper-folder>/Asset/` — Converter-owned extracted visual assets referenced by `original.md`.
- **Example**:

  ```json
  {
    "url_path": "/absolute/workspace/path/paper.pdf",
    "converter_handoff": "/absolute/workspace/path/Validated Paper/.conversion-manifest.json",
    "approval_state": "/absolute/workspace/path/.agents/scratch/ux-research-paper/<run-id>/approval.json",
    "approval_response": "approve APPROVE-TRANSLATE-TO-VIE:<sha256>"
  }
  ```

There is no `force`, overwrite, batch, or replacement option. If either output already exists, stop before Built-in-AI work.

## Output

- **Type**: `dict`
- **Format**:

  ```json
  {
    "status": "success",
    "url_path": "/requested/paper.pdf",
    "paper_folder": "/parent/Validated Paper Title",
    "voice_tone_md": "/parent/Validated Paper Title/voice-tone.md",
    "vie_md": "/parent/Validated Paper Title/vie.md",
    "source_language": "en",
    "copied_source": false,
    "validation": {
      "voice_tone": "passed",
      "coverage": "passed",
      "structure_parity": "passed",
      "audit": "passed"
    }
  }
  ```

- **Location**: `file_path`
- **Output File(s)**:
  - `<paper-folder>/voice-tone.md` — Complete author voice/tone analysis and translation rules written in Vietnamese.
  - `<paper-folder>/vie.md` — Full Vietnamese paper preserving source Markdown structure and protected content.

```text
Validated Paper Title/
├── original.md                 # converter output
├── voice-tone.md               # this skill
├── vie.md                      # this skill
├── Asset/                      # converter output
└── .conversion-manifest.json   # converter handoff
```

### `voice-tone.md` format

```markdown
# Phân tích giọng văn và sắc thái

## Metadata

- `schema_version`: voice-tone-v1
- `source_language`: en
- `source_block_count`: 123
- `analysis_language`: vi
- `source_sha256`: <sha256>
- `original_md_sha256`: <sha256>

## Hồ sơ giọng văn

- **Ngôi kể:** ...
- **Mức độ trang trọng:** ...
- **Lập trường học thuật:** ...
- **Mức độ chắc chắn:** ...
- **Nhịp và cấu trúc câu:** ...
- **Mật độ diễn đạt:** ...
- **Văn phong chuyên ngành:** ...
- **Cách lập luận và trình bày bằng chứng:** ...

## Quy tắc dịch bắt buộc

1. ...

## Thuật ngữ ưu tiên

| Thuật ngữ gốc | Cách dịch ưu tiên | Ghi chú sử dụng |
| --- | --- | --- |
| ... | ... | ... |

## Nội dung không được thay đổi

- ...

## Phạm vi phân tích

- **Các block đã phân tích:** b000001, ...
- **Đã bao phủ toàn bộ original.md:** có
```

## API Key

| Field | Value | Notes |
| --- | --- | --- |
| **Key** | `None` | Never read `.env`; no external AI API is used. |
| **Model** | `Built-in AI` | Host supplies structured voice, translation, and audit responses. |

## Custom Instructions

- Run `resolve` with the exact original `url_path` and explicit converter result/manifest. Never search broadly or guess the paper folder.
- Require exactly one successful `converter-manifest-v2` handoff. Reject zero or multiple papers.
- Verify manifest status, Docling `SUCCESS`, source identity, renamed PDF signature/hash, `original.md` hash, asset inventory/hashes, source-language confidence, and all absolute paths within the workspace.
- Create an approval token from canonical `approval-v1` data: `url_path`, source hash, Markdown hash, manifest hash, renamed PDF path, paper-folder path, and `original.md` path.
- Present the converter outputs and pause. Do not execute `prepare` in the same stage as conversion.
- Accept translation only after an affirmative response containing the exact token. Recompute all hashes and paths; invalidate and remove approval state after any change.
- Treat approval as single-use.
- Before creating approval, before AI task creation, and immediately before publication, deny execution if either `voice-tone.md` or `vie.md` exists.
- Parse `original.md` into stable source block IDs. Support ATX/Setext headings, escaped table pipes, multiline HTML/math, nested-list continuations, reference definitions, code fences, and mixed LF/CRLF while preserving blank lines and non-translatable syntax.
- Store the full block inventory once in a workspace-owned file. Voice requests reference `original.md` and the inventory by absolute path plus SHA-256 instead of embedding the paper.
- Ask Built-in AI for `voice-tone-v1` JSON in Vietnamese. Require every source block ID in exact order and all required voice-profile fields.
- Render `voice-tone.md` deterministically from validated JSON.
- For non-Vietnamese sources, partition translatable blocks under the configured block/character budgets. Write one independent `translation-v1` request per stable chunk with only its blocks and relevant voice/terminology rules; the host may execute independent requests safely in parallel.
- Persist `translation-chunks.json` plus validated per-chunk responses. Resume incomplete work without discarding previously validated chunks, then reassemble only after exact global coverage in source order.
- Translate all natural-language headings, paragraphs, captions, footnotes, list items, image alt text, and table cells fully. Do not summarize, simplify, omit, invent, merge, split, or reorder content.
- Preserve heading prefixes/levels, block order/count, table pipes/dimensions/cell occupancy, list/quote prefixes, image targets, link destinations, code fences/content, formulas, citations, URLs, DOIs, bibliography entries, identifiers, numbers, units, and symbols exactly.
- Reassemble `vie.md` by replacing only validated source block spans.
- For a confidently Vietnamese source, copy `original.md` byte-for-byte to staged `vie.md` after generating `voice-tone.md`.
- Build a compact audit inventory of block IDs, hashes, protected-token signatures, and contextual sample IDs. Audit requests reference `original.md`, `voice-tone.md`, `vie.md`, and the inventory by absolute path plus SHA-256; they never serialize complete document copies.
- Ask Built-in AI for a complete `translation-audit-v1` response. Require `passed: true` and an empty issues list.
- Run deterministic structure and protected-token parity after the AI audit; AI cannot override a parity failure.
- Retry malformed voice, translation, parity, or audit handoffs up to the configured attempt count while hashes/paths/outputs remain unchanged. Preserve validated prior phases, regenerate only the failing phase, and consume the approval state only after exhaustion, terminal invalidation, or success.
- When a semantic audit rejects a non-Vietnamese translation, preserve the validated voice profile, reset only translation chunks, pass audit feedback to the retry state, and remain under the same hash-bound approval.
- Stage files only under `<paper-folder>/.translation-staging/<run-id>/`.
- Acquire an exclusive paper-folder lock and create final outputs with exclusive creation. If the second file fails, remove only the first file created by this run.
- Clean owned staging and approval state after success or a terminal validation failure. Never delete unrelated files.

Runtime phases:

```bash
python3 -B .agents/workflows/ux-research-paper/skills/translate-to-vie/scripts/translate_to_vie.py resolve --url-path "<url_path>" --handoff-json "<converter-result-or-manifest.json>" --workspace-root "<workspace-root>"
python3 -B .agents/workflows/ux-research-paper/skills/translate-to-vie/scripts/translate_to_vie.py create-approval --resolved-json "<resolved.json>" --workspace-root "<workspace-root>"
python3 -B .agents/workflows/ux-research-paper/skills/translate-to-vie/scripts/translate_to_vie.py prepare --approval-state "<approval.json>" --approval-response "approve <exact-token>" --workspace-root "<workspace-root>" --max-blocks-per-chunk 80 --max-chars-per-chunk 24000 --max-tokens-per-chunk 6000 --max-ai-attempts 3
python3 -B .agents/workflows/ux-research-paper/skills/translate-to-vie/scripts/translate_to_vie.py build-voice-tone --state-json "<state.json>" --voice-tone-response "<voice.json>"
python3 -B .agents/workflows/ux-research-paper/skills/translate-to-vie/scripts/translate_to_vie.py build-translation --state-json "<state.json>" --translation-response "<translation-chunk.json>" # repeat for each pending chunk
python3 -B .agents/workflows/ux-research-paper/skills/translate-to-vie/scripts/translate_to_vie.py publish --state-json "<state.json>" --audit-response "<audit.json>"
```

Skip `build-translation` only when `source_language.language` is confidently `vi` and `build-voice-tone` created a byte-identical staged copy.

## Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Parent as UX Research Paper
    participant Skill as Translate Python
    participant Host as Built-in AI
    participant FS as Workspace Filesystem

    Parent->>Skill: Resolve exact converter handoff
    Skill->>FS: Verify PDF, original.md, assets, manifest and hashes
    Skill-->>Parent: Current hash-bound approval token
    Parent-->>User: Present original.md and request approval
    User-->>Parent: approve + exact token
    Parent->>Skill: Prepare with approval state and response
    Skill->>Skill: Recompute hashes; parse stable blocks
    Skill-->>Host: File-referenced voice-tone-v1 task
    Host-->>Skill: Vietnamese voice profile and rules
    Skill->>Skill: Validate coverage; render staged voice-tone.md
    alt Source is already Vietnamese
        Skill->>FS: Stage byte-identical vie.md
    else Translation required
        Skill->>Skill: Write bounded resumable chunk plan
        par Independent Built-in-AI chunk tasks
            Skill-->>Host: translation-v1 chunk requests
            Host-->>Skill: One result per source block
        end
        Skill->>Skill: Validate chunks and deterministic global reassembly
    end
    Skill-->>Host: File-referenced compact translation-audit-v1 task
    Host-->>Skill: Passing audit
    Skill->>Skill: Re-run deterministic parity
    Skill->>FS: Exclusively publish voice-tone.md and vie.md
    Skill-->>Parent: Final paths and validation status
    Parent-->>User: Translation complete
```

## Error Handling & Fallbacks

| Error Code | Message | Fallback Behavior |
| --- | --- | --- |
| `INVALID_INPUT` | Required input/JSON is missing or malformed. | Request the exact URL/path or valid JSON artifact. |
| `NO_PDFS_DISCOVERED` | No converted paper resolved. | Run converter with one exact PDF. |
| `MULTIPLE_PDFS_DISCOVERED` | More than one paper resolved. | Request one exact PDF URL/path. |
| `HANDOFF_NOT_FOUND`, `HANDOFF_SCHEMA_INVALID` | Converter handoff is missing/invalid. | Re-run converter. |
| `CONVERSION_NOT_SUCCESSFUL` | Converter/Docling did not fully succeed. | Stop before approval/translation. |
| `SOURCE_IDENTITY_MISMATCH` | URL/path identity does not match manifest. | Use the original converter input. |
| `PAPER_FOLDER_MISSING`, `ORIGINAL_MD_MISSING` | Required converter output is absent. | Re-run converter. |
| `SOURCE_HASH_MISMATCH`, `APPROVAL_INVALID` | Source, Markdown, manifest, or paths changed. | Invalidate approval and request a fresh run/approval. |
| `NOT_APPROVED` | Response lacks affirmative intent or exact token. | Remain paused. |
| `OUTPUT_EXISTS` | Either target already exists. | Deny replacement; user must intentionally move/delete it before a new run. |
| `VOICE_TONE_SCHEMA_INVALID`, `VOICE_TONE_NOT_VIETNAMESE`, `VOICE_TONE_COVERAGE_FAILED` | Voice analysis is malformed, non-Vietnamese, or incomplete. | Preserve approval/staging and retry only voice analysis up to the bounded attempt count. |
| `TRANSLATION_SCHEMA_INVALID`, `TRANSLATION_BLOCK_MISSING`, `TRANSLATION_BLOCK_DUPLICATE`, `TRANSLATION_BLOCK_REORDERED`, `TRANSLATION_BLOCK_MERGED`, `TRANSLATION_BLOCK_SPLIT` | Translation block contract failed. | Preserve validated chunks and retry only the failing chunk while inputs remain unchanged. |
| `PROTECTED_TOKEN_CHANGED`, `MARKDOWN_STRUCTURE_MISMATCH` | Protected content/structure changed. | Retry the AI-produced failing translation phase; deterministic/tamper failures remain terminal. |
| `AI_AUDIT_FAILED` | Audit is malformed or found unresolved translation/voice issues. | Retry audit schema failures; reset only translation chunks after semantic rejection; clean state after attempt exhaustion. |
| `RESOURCE_REVIEW_REQUIRED` | Source/block/chunk limits would be exceeded. | Restore approval to awaiting state and report exact measured/configured limits. |
| `PUBLICATION_FAILED`, `ROLLBACK_FAILED` | Two-file publication could not complete safely. | Preserve pre-existing files and report exact paths. |
| `CLEANUP_FAILED` | Owned temporary artifacts remain. | Report exact paths; never delete unrelated files. |

## Known Bugs & Resolutions

> **Agent Rule:** After successfully fixing a runtime bug, document its cause, resolution, and regression test here.

| Bug / Error | Cause | Resolution |
| --- | --- | --- |
| Malformed state with an empty cleanup path could resolve to the current workspace directory | `Path("")` resolves to the current directory, and the initial cleanup helper did not require paths to stay under translator-owned roots. | Require non-empty paths and allowlist cleanup to `<paper-folder>/.translation-staging/<run-id>/` and `.agents/scratch/ux-research-paper/<run-id>/`; added a regression test proving empty/unowned paths preserve workspace files. |
| A translation-budget rejection could leave approval marked as consumed before staging existed | Approval was validated and marked `approved` before source-size/block budgets were enforced. | Restore the same hash-bound approval state to `awaiting_approval` when budget review is required; regression test verifies resumability. |

## Performance Improvement Solutions

### Execution Efficiency

- [x] Translate in bounded chunks keyed by stable block IDs, allow safe parallel Built-in-AI translation of independent chunks, and preserve deterministic ordering before the global audit.
- [x] Replace full-document JSON embedding with workspace file references plus hashes; send each translation chunk only the source blocks and minimum voice/terminology rules it needs.
- [x] Make the final audit request a compact inventory of block IDs, hashes, protected-token signatures, and contextual evidence while allowing Built-in AI to read the three staged files directly.

### Workflow Fit

- [x] Classify AI schema, coverage, and parity failures as retryable while approval-bound inputs remain unchanged; retain validated earlier phases and regenerate only the failing phase within a bounded attempt count.

### Reliability & Error Handling

- [x] Extend parser/signature rules and deterministic fixtures for Setext headings, escaped table pipes, multiline HTML/math, nested-list continuations, reference definitions, and mixed CRLF input.
- [x] Add orchestrator-managed bounded retries for retryable Built-in-AI schema, coverage, and audit failures, using validation details to constrain each retry prompt.

### Cost & Scalability

- [x] Add configurable block/token budgets, per-chunk request/response files, resumable chunk manifests, and a final global coverage/parity pass.
- [x] Reference staged files by absolute workspace path and hash in audit tasks instead of serializing complete document copies into JSON.
