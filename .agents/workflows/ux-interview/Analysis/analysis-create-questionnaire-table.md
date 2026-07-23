# Skill Performance Analysis: create-questionnaire-table

> Last updated: 2026-07-22

---

## 1. ⚡ Execution Efficiency

| Criteria | 2026-07-13 | 2026-07-22 |
|----------|----------|----------|
| Execution Time | • **8/10** — Single image processed in one AI vision call with no redundant reads. Efficient for single-image input. | • **7/10** — Extraction is sequential across every image and may repeat up to three vision passes; ordering is not defined. • **Solution**: Implemented deterministic ordering, bounded batches, and a 20-image limit. |
| API Call Count | • **9/10** — No external API calls. Uses only built-in AI vision. Minimal overhead. | • **9/10** — Uses built-in vision only; no paid or redundant external calls are specified. • No improvement needed. |
| Token Usage | • **7/10** — AI processes the full image and generates the table. No unnecessary context, but output instructions could be tighter to reduce token waste. | • **8/10** — Output is tightly constrained to a heading and table, and retries occur only after validation fails. • No improvement needed. |
| Resource Consumption | • **8/10** — No temp files created. Image is read in-place. Cleanup instruction exists in SKILL.md. | • **7/10** — Invalid output is removed before retries, but no page-count or image-size guard is stated. • **Solution**: Implemented a 20-image and 20 MB-per-image limit with an actionable error. |

---

## 2. 🎯 Output Quality & Accuracy

| Criteria | 2026-07-13 | 2026-07-22 |
|----------|----------|----------|
| Output Completeness | • **7/10** — Output schema defines status, image_file, output_file. However, there is no programmatic validation that the generated table has the correct structure. | • **7/10** — The contract names one image_file while instructions support multiple images and omit terminal validator details. • **Solution**: Implemented an `image_files` array and terminal validator detail requirement. |
| Format Compliance | • **6/10** — Format is well-specified in SKILL.md with examples, but enforcement relies entirely on AI instruction-following with no automated validation. | • **7/10** — Validator enforces structure but accepts extra prose or tables and cannot safely handle literal pipes in cells. • **Solution**: Implemented canonical one-heading/one-table validation with escaped-pipe support. |
| Content Accuracy | • **8/10** — Good anti-hallucination measures: preserves Vietnamese text, auto-generates # numbering, handles optional Topic column, cleans newlines and HTML tags. | • **7/10** — Structural validation and visual review help, but no source-fidelity check detects missed or invented content. • **Solution**: Implemented a page-coverage, row-count, sequence, and mandatory-field checklist. |
| Human Approval Rate | • **7/10** — No bugs logged yet, but no tests exist to catch regressions. The lack of self-verification means extraction errors may reach the user. | • **7/10** — Current tests cover core structure, but source-fidelity and complex Markdown cases remain untested. • **Solution**: Added Vietnamese, literal-pipe, extra-prose, duplicate-table, and separator regression coverage. |

---

## 3. 🔗 Workflow Fit

| Criteria | 2026-07-13 | 2026-07-22 |
|----------|----------|----------|
| I/O Contract Adherence | • **9/10** — Output filename full-questionnaire.md matches exactly what downstream skills (map-transcript, transcribe-audios orchestrator flow) expect. | • **7/10** — Output path fits the workflow, but single-image prerequisites conflict with multi-page instructions and schema. • **Solution**: Aligned prerequisites, multi-page instructions, and the `image_files` output contract. |
| Skip-Logic Compatibility | • **8/10** — Orchestrator incremental execution checks for existing full-questionnaire.md. Skill overwrites on re-run, so skip-logic works correctly. | • **6/10** — Existing output causes success without validation, so corrupt or partial files block regeneration. • **Solution**: Implemented cached-output validation and invalid-output regeneration guidance. |
| Pipeline Passthrough Rate | • **8/10** — 5 error codes defined covering all major failure modes. Orchestrator handles UNKNOWN_INTENT and SKILL_FAILURE generically. | • **8/10** — Error codes, validation retries, and cleanup prevent most malformed output from reaching downstream steps. • No improvement needed. |
| Idempotency | • **8/10** — Same image input produces same output. Uses write_to_file which overwrites. No side effects. | • **6/10** — Invalid cached output is accepted and regenerated AI output is not deterministic. • **Solution**: Implemented validator-gated caching and deterministic input ordering. |

---

## 4. 🛡️ Reliability & Error Handling

| Criteria | 2026-07-13 | 2026-07-22 |
|----------|----------|----------|
| Error Rate | • **7/10** — 5 error codes cover most scenarios, but missing WRITE_FAILURE for file system errors (permission denied, disk full). | • **7/10** — Common errors are handled, but validator exceptions, invalid cached output, and input-size failures are not explicit. • **Solution**: Added read, validation, and bounded-input error guidance with cleanup. |
| Error Recoverability | • **6/10** — No explicit instructions for cleaning up partially written files on failure. A malformed full-questionnaire.md could confuse downstream skills. | • **7/10** — Invalid generated output is cleaned and retried, but cached-output recovery bypasses validation. • **Solution**: Added cached-output validation, cleanup, and terminal validator diagnostics. |
| Retry Success Rate | • **5/10** — No retry mechanism exists. If AI misreads the image on first attempt, the skill fails without retry. | • **7/10** — Three attempts recover from vision mistakes, though retries are not tailored to failure type. • **Solution**: Limited retries to interpretation and structural-validation failures. |
| Known Bug Recurrence | • **6/10** — No bugs logged and no tests exist. This means bugs may exist but are undetected, and there is no regression prevention. | • **6/10** — No bugs are documented and tests miss parsing and skip-logic regressions. • **Solution**: Added a documented resolution and parser/CLI regression tests. |

---

## 5. 💰 Cost & Scalability

| Criteria | 2026-07-13 | 2026-07-22 |
|----------|----------|----------|
| Cost per Execution | • **7/10** — No paid APIs. Uses built-in AI vision. But no skip logic within the skill itself to avoid redundant AI calls if output already exists. | • **8/10** — No external paid APIs and valid existing output avoids repeat vision work. • No improvement needed. |
| Scaling Behavior | • **6/10** — Limited to exactly 1 image. Multi-page questionnaires require manual splitting. No instructions for handling multi-page scenarios. | • **6/10** — Multi-page work is linear in image count and retries can multiply cost, with no documented upper bound. • **Solution**: Implemented sorted bounded batches, progress reporting, and input limits. |
| Unit Test Coverage & Pass Rate | • **4/10** — No tests directory, no test files, no validation script. This is the lowest coverage of any skill in the workflow. | • **7/10** — Eight unit tests cover core table and numbering paths but omit parser edge cases and CLI behavior. • **Solution**: Added tests for empty documents, headers, extra content, pipes, duplicate tables, and CLI exits. |
