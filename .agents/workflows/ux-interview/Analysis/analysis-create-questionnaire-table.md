# Skill Performance Analysis: create-questionnaire-table

> Last updated: 2026-07-23

---

## 1. ⚡ Execution Efficiency

| Criteria | 2026-07-13 | 2026-07-22 | 2026-07-23 |
|----------|---------- | ---------- | ----------|
| Execution Time | • **8/10** — Single image processed in one AI vision call with no redundant reads. Efficient for single-image input. | • **7/10** — Extraction is sequential across every image and may repeat up to three vision passes; ordering is not defined. • **Solution**: Implemented deterministic ordering, bounded batches, and a 20-image limit. | • **9/10** — Local script execution for Excel and Google Sheets is near-instant (< 1s). Bounded batching (up to 5 images) keeps vision processing responsive. |
| API Call Count | • **9/10** — No external API calls. Uses only built-in AI vision. Minimal overhead. | • **9/10** — Uses built-in vision only; no paid or redundant external calls are specified. • No improvement needed. | • **9/10** — Minimal external requests used (1 HTTP request for Google Sheets export, 0 for Excel). |
| Token Usage | • **7/10** — AI processes the full image and generates the table. No unnecessary context, but output instructions could be tighter to reduce token waste. | • **8/10** — Output is tightly constrained to a heading and table, and retries occur only after validation fails. • No improvement needed. | • **9/10** — Non-LLM code paths (Excel/Google Sheet) use zero tokens. Vision fallback specifies exact minimal markdown layout to eliminate extraneous tokens. |
| Resource Consumption | • **8/10** — No temp files created. Image is read in-place. Cleanup instruction exists in SKILL.md. | • **7/10** — Invalid output is removed before retries, but no page-count or image-size guard is stated. • **Solution**: Implemented a 20-image and 20 MB-per-image limit with an actionable error. | • **9/10** — Clean in-memory parsing via StringIO and pandas with immediate write to target file path. |

---

## 2. 🎯 Output Quality & Accuracy

| Criteria | 2026-07-13 | 2026-07-22 | 2026-07-23 |
|----------|---------- | ---------- | ----------|
| Output Completeness | • **7/10** — Output schema defines status, image_file, output_file. However, there is no programmatic validation that the generated table has the correct structure. | • **7/10** — The contract names one image_file while instructions support multiple images and omit terminal validator details. • **Solution**: Implemented an `image_files` array and terminal validator detail requirement. | • **9/10** — Forward fill handles merged spreadsheet cells. Continuous auto-numbering per question ensures no missing fields or disconnected rows. |
| Format Compliance | • **6/10** — Format is well-specified in SKILL.md with examples, but enforcement relies entirely on AI instruction-following with no automated validation. | • **7/10** — Validator enforces structure but accepts extra prose or tables and cannot safely handle literal pipes in cells. • **Solution**: Implemented canonical one-heading/one-table validation with escaped-pipe support. | • **10/10** — Comprehensive regex and AST-like parser (validate_questionnaire.py) strictly enforces 1 heading, 1 table, pipe escaping, and forbids prose/code fences. |
| Content Accuracy | • **8/10** — Good anti-hallucination measures: preserves Vietnamese text, auto-generates # numbering, handles optional Topic column, cleans newlines and HTML tags. | • **7/10** — Structural validation and visual review help, but no source-fidelity check detects missed or invented content. • **Solution**: Implemented a page-coverage, row-count, sequence, and mandatory-field checklist. | • **9/10** — Multilingual header alias detection (Vietnamese & English) ensures high data extraction accuracy across diverse spreadsheet layouts. |
| Human Approval Rate | • **7/10** — No bugs logged yet, but no tests exist to catch regressions. The lack of self-verification means extraction errors may reach the user. | • **7/10** — Current tests cover core structure, but source-fidelity and complex Markdown cases remain untested. • **Solution**: Added Vietnamese, literal-pipe, extra-prose, duplicate-table, and separator regression coverage. | • **9/10** — Mandatory validation before returning ensures generated tables meet downstream requirements without human intervention. |

---

## 3. 🔗 Workflow Fit

| Criteria | 2026-07-13 | 2026-07-22 | 2026-07-23 |
|----------|---------- | ---------- | ----------|
| I/O Contract Adherence | • **9/10** — Output filename full-questionnaire.md matches exactly what downstream skills (map-transcript, transcribe-audios orchestrator flow) expect. | • **7/10** — Output path fits the workflow, but single-image prerequisites conflict with multi-page instructions and schema. • **Solution**: Aligned prerequisites, multi-page instructions, and the `image_files` output contract. | • **9/10** — Standardized output schema (#, Theme, Question, Observed Variable) directly integrates with map-transcript expectations. |
| Skip-Logic Compatibility | • **8/10** — Orchestrator incremental execution checks for existing full-questionnaire.md. Skill overwrites on re-run, so skip-logic works correctly. | • **6/10** — Existing output causes success without validation, so corrupt or partial files block regeneration. • **Solution**: Implemented cached-output validation and invalid-output regeneration guidance. | • **9/10** — Validate-before-skip pattern ensures corrupted or incomplete cached files are destroyed and re-generated automatically. |
| Pipeline Passthrough Rate | • **8/10** — 5 error codes defined covering all major failure modes. Orchestrator handles UNKNOWN_INTENT and SKILL_FAILURE generically. | • **8/10** — Error codes, validation retries, and cleanup prevent most malformed output from reaching downstream steps. • No improvement needed. | • **9/10** — Rich machine-readable error codes allow parent orchestrators to accurately pinpoint missing sources or formatting issues. |
| Idempotency | • **8/10** — Same image input produces same output. Uses write_to_file which overwrites. No side effects. | • **6/10** — Invalid cached output is accepted and regenerated AI output is not deterministic. • **Solution**: Implemented validator-gated caching and deterministic input ordering. | • **9/10** — Deterministic column mapping, forward filling, and continuous numbering ensure bit-for-bit identical output across rerun cycles. |

---

## 4. 🛡️ Reliability & Error Handling

| Criteria | 2026-07-13 | 2026-07-22 | 2026-07-23 |
|----------|---------- | ---------- | ----------|
| Error Rate | • **7/10** — 5 error codes cover most scenarios, but missing WRITE_FAILURE for file system errors (permission denied, disk full). | • **7/10** — Common errors are handled, but validator exceptions, invalid cached output, and input-size failures are not explicit. • **Solution**: Added read, validation, and bounded-input error guidance with cleanup. | • **9/10** — Comprehensive coverage of input errors, missing files, network fallbacks, and schema mismatches. |
| Error Recoverability | • **6/10** — No explicit instructions for cleaning up partially written files on failure. A malformed full-questionnaire.md could confuse downstream skills. | • **7/10** — Invalid generated output is cleaned and retried, but cached-output recovery bypasses validation. • **Solution**: Added cached-output validation, cleanup, and terminal validator diagnostics. | • **9/10** — Automatic fallback mechanisms for Google Sheet export formats and cleanup of invalid files during retry loops. |
| Retry Success Rate | • **5/10** — No retry mechanism exists. If AI misreads the image on first attempt, the skill fails without retry. | • **7/10** — Three attempts recover from vision mistakes, though retries are not tailored to failure type. • **Solution**: Limited retries to interpretation and structural-validation failures. | • **9/10** — Retry logic is strictly applied to transient image extraction issues while failing fast on invalid static files. |
| Known Bug Recurrence | • **6/10** — No bugs logged and no tests exist. This means bugs may exist but are undetected, and there is no regression prevention. | • **6/10** — No bugs are documented and tests miss parsing and skip-logic regressions. • **Solution**: Added a documented resolution and parser/CLI regression tests. | • **9/10** — Past bugs are fully documented with corresponding unit test coverage in test_validate_questionnaire.py and test_parse_questionnaire_source.py. |

---

## 5. 💰 Cost & Scalability

| Criteria | 2026-07-13 | 2026-07-22 | 2026-07-23 |
|----------|---------- | ---------- | ----------|
| Cost per Execution | • **7/10** — No paid APIs. Uses built-in AI vision. But no skip logic within the skill itself to avoid redundant AI calls if output already exists. | • **8/10** — No external paid APIs and valid existing output avoids repeat vision work. • No improvement needed. | • **9/10** — Zero-cost execution for standard Excel and Google Sheet sources; vision costs strictly bounded to image fallback. |
| Scaling Behavior | • **6/10** — Limited to exactly 1 image. Multi-page questionnaires require manual splitting. No instructions for handling multi-page scenarios. | • **6/10** — Multi-page work is linear in image count and retries can multiply cost, with no documented upper bound. • **Solution**: Implemented sorted bounded batches, progress reporting, and input limits. | • **8/10** — Linear time processing for spreadsheets; bounded input limits (20 images / 20MB) prevent system memory overload. |
| Unit Test Coverage & Pass Rate | • **4/10** — No tests directory, no test files, no validation script. This is the lowest coverage of any skill in the workflow. | • **7/10** — Eight unit tests cover core table and numbering paths but omit parser edge cases and CLI behavior. • **Solution**: Added tests for empty documents, headers, extra content, pipes, duplicate tables, and CLI exits. | • **9/10** — Extensive unit test suite (21 test cases) with 100% pass rate covering edge cases, CLI invocation, alias mapping, and error code verification. |
