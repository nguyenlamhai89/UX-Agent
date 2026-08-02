# Skill Performance Analysis: translate-to-vie

> Last updated: 2026-08-02

---

## 1. ⚡ Execution Efficiency

| Criteria | 2026-08-02 |
|----------|----------|
| Execution Time | • **7/10** — The workflow uses deterministic parsing and avoids translation for confidently Vietnamese sources, but non-Vietnamese papers require sequential voice analysis, translation, and audit phases and there is no implemented bounded chunk scheduler for long papers. |
| API Call Count | • **8/10** — There are no external paid API calls. The three Built-in-AI phases are purposeful quality gates, and Vietnamese sources skip the translation phase. |
| Token Usage | • **5/10** — The voice task includes every raw block, the translation task repeats all translatable blocks plus the rendered voice profile, and audit-request.json embeds full copies of original.md, voice-tone.md, and vie.md. Long papers therefore duplicate content across disk and Built-in-AI contexts. |
| Resource Consumption | • **8/10** — Approval and translation staging are workspace-owned, terminal failures and success clean owned state, publication uses exclusive files and a lock, and the cleanup allowlist prevents unowned deletion. Request JSON duplication can still be large but is bounded by one paper. |

---

## 2. 🎯 Output Quality & Accuracy

| Criteria | 2026-08-02 |
|----------|----------|
| Output Completeness | • **9/10** — The result and both exact output files are fully specified; voice-tone.md includes metadata, eight profile dimensions, rules, terminology, protected content, and complete block coverage; vie.md has a strict full-translation contract. |
| Format Compliance | • **8/10** — Structured AI schemas, deterministic rendering, stable block IDs, exclusive filenames, and parity signatures enforce the documented format. The custom line-oriented parser covers common Docling Markdown but not every CommonMark construct. |
| Content Accuracy | • **8/10** — Exact source hashes, one-to-one block coverage, protected-token checks, deterministic reassembly, a full Built-in-AI audit, and post-audit parity strongly limit omission and drift; semantic translation quality still depends on Built-in AI and lacks real-paper acceptance fixtures. |
| Human Approval Rate | • **8/10** — Users explicitly approve the exact converted source before translation, existing outputs are preserved, and failures publish neither file. No production acceptance history is yet available. |

---

## 3. 🔗 Workflow Fit

| Criteria | 2026-08-02 |
|----------|----------|
| I/O Contract Adherence | • **9/10** — The resolver enforces converter-manifest-v2 fields and hashes exactly, and the orchestrator passes the original url_path, explicit handoff, approval state, and token expected by the skill; workflow E2E covers the complete sequence. |
| Skip-Logic Compatibility | • **8/10** — The skill intentionally denies replacement instead of silently skipping, which matches the user's requirement and prevents stale or partial translations from being mistaken for success. |
| Pipeline Passthrough Rate | • **7/10** — Hash-bound approval and strict validation protect quality, but any malformed voice/translation response currently cleans staging and consumes approval, forcing a fresh approval cycle rather than regenerating only the failing AI phase while inputs are unchanged. |
| Idempotency | • **9/10** — Approval is single-use, inputs are hash-bound, outputs use exclusive creation, existing files are never replaced, and second-file failure rolls back the first newly created output. |

---

## 4. 🛡️ Reliability & Error Handling

| Criteria | 2026-08-02 |
|----------|----------|
| Error Rate | • **7/10** — Stable error codes and tests cover the main handoff, approval, block, parity, audit, publication, and cleanup failures. The line-oriented parser does not yet explicitly support or test Setext headings, escaped table pipes, multiline HTML/math, nested-list continuations, or reference-definition variants. |
| Error Recoverability | • **8/10** — Hash changes invalidate stale approval, NOT_APPROVED remains resumable, terminal failures publish nothing, publication rollback is tested, and cleanup is allowlisted to owned roots after the empty-path regression fix. |
| Retry Success Rate | • **5/10** — No bounded retry/regeneration policy exists for malformed Built-in-AI voice, translation, or audit responses; validation failures currently clean state and require a new approval flow. |
| Known Bug Recurrence | • **9/10** — The discovered empty-path cleanup hazard was fixed at the root with owned-root allowlisting and a regression test that preserves a workspace sentinel; no recurring bug pattern is present. |

---

## 5. 💰 Cost & Scalability

| Criteria | 2026-08-02 |
|----------|----------|
| Cost per Execution | • **9/10** — The skill uses no paid external service or external LLM SDK; cost is host Built-in-AI inference plus local deterministic parsing and file I/O. |
| Scaling Behavior | • **5/10** — Parsing and reassembly are approximately linear, but all blocks are placed in single voice/translation request files, audit duplicates three complete documents, responses are expected as one global block list, and no context/resource budget is enforced. |
| Unit Test Coverage & Pass Rate | • **8/10** — Fourteen translator tests plus four workflow E2E tests pass and cover handoff, approval, tampering, existing outputs, voice coverage, protected numbers, parity, English/Vietnamese success, audit failure, rollback, cleanup safety, and converter failure. Complex real-world Markdown and long-document chunking are not yet covered. |

---

## Remediation Status

> Implemented after this pre-remediation baseline on 2026-08-02.

- [x] Added bounded stable-ID translation chunks, independent parallel-safe request files, deterministic reassembly, and a resumable chunk manifest.
- [x] Replaced complete-document voice/audit JSON payloads with workspace file references and SHA-256; chunk requests carry only scoped blocks and relevant rules/terms.
- [x] Added a compact audit inventory with block hashes, protected-token signatures, and contextual sample IDs.
- [x] Added bounded phase-specific retries that preserve unchanged approval and validated prior work, including semantic-audit translation reset.
- [x] Expanded deterministic parsing/signatures and fixtures for Setext headings, escaped pipes, multiline HTML/math, nested-list continuations, reference definitions, and CRLF.
- [x] Added configurable source/block/chunk/context budgets and retry-attempt limits.

Post-remediation validation target: 21 translator tests plus 5 workflow E2E tests. The scores above intentionally remain the historical baseline that produced these recommendations.
