# Skill Performance Analysis: convert-researchpaper-to-md

> Last updated: 2026-08-02

---

## 1. ⚡ Execution Efficiency

| Criteria | 2026-08-02 |
|----------|----------|
| Execution Time | • **7/10** — The pipeline avoids full conversion until title approval and skips full Docling work when a valid manifest is found, but a repeated run still performs PDF discovery, Docling title preflight, and Built-in-AI title validation before the manifest skip gate. |
| API Call Count | • **8/10** — There are no paid external API calls. A normal run uses only three focused Built-in-AI decisions for title, language, and source audit, while deterministic Python and Docling own extraction and validation. |
| Token Usage | • **7/10** — Title and language prompts are bounded, but the source-completeness audit may require original.md plus a large lossless Docling inventory and page evidence, which can grow substantially for long papers. |
| Resource Consumption | • **6/10** — Per-paper conversion staging is removed after publication and downloads are bounded to 100 MiB, but remote responses are held in memory, preflight job directories are not removed by the runtime, and empty incoming hash directories can remain after remote files are moved. |

---

## 2. 🎯 Output Quality & Accuracy

| Criteria | 2026-08-02 |
|----------|----------|
| Output Completeness | • **9/10** — The source-only contract is explicit and the manifest records every downstream path, source/artifact hash, source language, Docling status/version, and asset inventory required by translate-to-vie. |
| Format Compliance | • **9/10** — Exact filenames, output tree, manifest schema, progress phases, title schema, language schema, and audit schema are documented and enforced by deterministic publication and validation code. |
| Content Accuracy | • **9/10** — Docling remains the canonical extractor; only SUCCESS is accepted; hybrid OCR has a full-page fallback; lossless inventory, page coverage, placeholders, assets, and a source audit all fail closed before publication. |
| Human Approval Rate | • **8/10** — Title confidence and source audit prevent low-quality handoffs, and the two known output-affecting bugs have root-cause fixes and regression tests. Real-paper acceptance data is not yet available. |

---

## 3. 🔗 Workflow Fit

| Criteria | 2026-08-02 |
|----------|----------|
| I/O Contract Adherence | • **9/10** — converter-manifest-v2 matches the translator resolver exactly, including original public url_path, renamed PDF, paper folder, original.md, Asset, source language, and hashes; workflow E2E validates this handoff. |
| Skip-Logic Compatibility | • **7/10** — Artifact hashes make skip decisions trustworthy and force rebuild preserves translator files, but skip is checked only after title preflight and callers must use the renamed PDF or explicit handoff because the original direct local path no longer exists. |
| Pipeline Passthrough Rate | • **8/10** — Stable error codes and fail-closed gates deliberately stop unsafe papers, while one-paper enforcement removes batch ambiguity and successful manifests pass directly to approval creation. |
| Idempotency | • **8/10** — Valid manifests are hash-checked, collision naming is deterministic, force rebuild is staged, and translator outputs are preserved. The durable PDF rename means callers should resume from the returned handoff rather than the obsolete original path. |

---

## 4. 🛡️ Reliability & Error Handling

| Criteria | 2026-08-02 |
|----------|----------|
| Error Rate | • **8/10** — The runtime defines stable failures for path safety, remote input, title, Docling, OCR, content, assets, language, audit, rename, and publication; unit and workflow tests cover the highest-risk paths. |
| Error Recoverability | • **7/10** — Transactional publication restores converter-owned artifacts and later failures preserve a verified title rename, but owned preflight/incoming scratch cleanup is incomplete and remote fetch failures provide only a generic terminal error. |
| Retry Success Rate | • **5/10** — The OCR fallback is appropriate, but transient DNS, connection, timeout, HTTP 429, and HTTP 5xx failures are not distinguished or retried; all remote fetch exceptions become REMOTE_FETCH_FAILED. |
| Known Bug Recurrence | • **9/10** — Both recorded bugs document causes and preventive fixes, and regression tests retain the literal PDF fixture signature and remote rename-before-output-parent ordering. |

---

## 5. 💰 Cost & Scalability

| Criteria | 2026-08-02 |
|----------|----------|
| Cost per Execution | • **9/10** — No paid external API or external LLM SDK is used. Cost is limited to local Docling/OCR compute and host Built-in-AI title, language, and audit inference. |
| Scaling Behavior | • **6/10** — Work is linear per page/item for one paper, but full remote responses are buffered, page renders and lossless inventory can be large, no explicit page-count limit exists, and a long source audit can exceed practical context limits. |
| Unit Test Coverage & Pass Rate | • **8/10** — Twenty converter tests plus four workflow E2E tests pass and cover title selection, discovery, remote ordering, Docling options, OCR coverage, manifest tampering, rollback, source-only output, and translator preservation. Actual Docling smoke fixtures and transient-network behavior remain untested. |

---

## Remediation Status

> Implemented after this pre-remediation baseline on 2026-08-02.

- [x] Added prior-handoff inspection before discovery, Docling preflight, and title AI, with unit and workflow E2E regression coverage.
- [x] Added bounded source-audit plans keyed by Docling item/page IDs and required complete ordered final synthesis.
- [x] Added centralized allowlisted cleanup for preflight/incoming scratch with exact removed/retained path details.
- [x] Added streamed PDF downloads with hashing and bounded exponential-backoff retry only for transient network/429/5xx failures.
- [x] Added configurable PDF-byte, page-count, staging-disk, and audit-chunk budgets with `RESOURCE_REVIEW_REQUIRED` details.

Post-remediation validation target: 26 converter tests plus 5 workflow E2E tests. The scores above intentionally remain the historical baseline that produced these recommendations.
