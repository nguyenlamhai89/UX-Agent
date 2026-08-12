# Skill Performance Analysis: clean-data-xlsx

> Last updated: 2026-08-12

---

## 1. ⚡ Execution Efficiency

| Criteria | 2026-08-12 | 2026-08-12 |
|----------|---------- | ----------|
| Execution Time | • **9/10** — Formula counting was integrated directly into the single-pass column inspection loop in inspect_and_clean(). • **Solution**: Combined formula counting directly into the primary column inspection loop instead of performing a redundant full pass over all cells via ws.iter_rows(). | • **7/10** — inspect_and_clean() walks data cells for profiling, then performs a second full data-row walk for deduplication; it also separately scans pre-header cells for formulas. • **Solution**: Combine profiling and duplicate-signature collection where safe, and add a large-workbook benchmark with an explicit performance budget. |
| API Call Count | • **10/10** — Zero external API calls are made. The skill runs entirely in local Python using openpyxl and pandas. | • **10/10** — The skill makes no external API calls; all work occurs locally. |
| Token Usage | • **10/10** — Uses zero LLM tokens; processing is 100% deterministic local Python execution. | • **10/10** — The deterministic Python implementation uses no LLM tokens. |
| Resource Consumption | • **8/10** — Creates temporary staging folders via tempfile.mkdtemp and cleans them up reliably in a try/finally block. Memory usage is proportional to workbook size in openpyxl. | • **8/10** — Staging is cleaned in finally blocks and SHA-256 is streamed, but openpyxl loads complete workbooks and reports retain per-cell changes in memory. |

---

## 2. 🎯 Output Quality & Accuracy

| Criteria | 2026-08-12 | 2026-08-12 |
|----------|---------- | ----------|
| Output Completeness | • **9/10** — Produces a complete set of 5 output artifacts including cleaned workbook, standalone replay script clean.py, bit-identical raw archive, 9-sheet data quality report, and cleaning_log.json. | • **8/10** — Five expected artifacts and structured success paths are produced, but the documented confirmation table has no executable inspection/confirmation interface. |
| Format Compliance | • **9/10** — Enforces strict output folder hierarchy (<stem>/, Scripts/, Analysis/). Past issue with double file extensions was resolved. | • **6/10** — The implementation emits undocumented error codes and always auto-converts user_id/casa-avg-12/td-avg-12 even though the contract requires user confirmation; the log simultaneously declares TYPE_CONVERSION_DISABLED. • **Solution**: Make conversion choices explicit input parameters gated by confirmation, then align SKILL.md, error codes, rules, and log entries with the actual behavior. |
| Content Accuracy | • **9/10** — Non-destructive cleaning logic preserves formula cells, merged ranges, leading zeros in string identifiers, and un-identifiable headers safely. | • **6/10** — The conservative defaults are strong, but blanks in casa-avg-12 and td-avg-12 are converted to 0 without confirmation, contradicting the no-imputation rule and risking data changes. • **Solution**: Remove automatic header-name conversions or require explicit confirmed conversion settings; add regression tests proving blanks stay blank by default. |
| Human Approval Rate | • **8/10** — High human approval rate due to zero data loss philosophy (flags mixed types/outliers rather than mutating them). Known bugs are documented and fixed. | • **6/10** — Raw archiving and reports support review, but undocumented automatic conversions and the missing confirmation gate can undermine trust in a safety-focused cleaner. • **Solution**: Expose a preview/confirmation result before mutation and include every confirmed transformation in the cleaning log. |

---

## 3. 🔗 Workflow Fit

| Criteria | 2026-08-12 | 2026-08-12 |
|----------|---------- | ----------|
| I/O Contract Adherence | • **9/10** — Input contract accepts standard JSON with input_xlsx_path; output returns structured dictionary containing file paths, hashes, and warnings. | • **6/10** — SKILL.md declares a dict input and mandatory interactive confirmation, while the CLI accepts only one positional path and clean_workbook has no confirmation or conversion-options argument. • **Solution**: Define one callable input schema and implement its confirmation/conversion fields consistently in the CLI, Python API, SKILL.md, and result JSON. |
| Skip-Logic Compatibility | • **9/10** — existing_output_is_valid() validates source SHA-256 against raw archive and log metadata, making skip-logic checks reliable. | • **8/10** — existing_output_is_valid() checks required derivatives and raw/log source hashes before refresh, preventing a mismatched source from being overwritten. |
| Pipeline Passthrough Rate | • **8/10** — Properly defines explicit error codes (INPUT_NOT_FOUND, UNSUPPORTED_EXTENSION, INVALID_XLSX, RAW_ARCHIVE_HASH_MISMATCH, etc.) without silent crashes. | • **7/10** — Most failures return CleanDataError codes, but several emitted codes are absent from the documented fallback table and generic exceptions expose raw messages as INTERNAL_ERROR. • **Solution**: Document every emitted error code and normalize unexpected exceptions into stable sanitized diagnostics with targeted tests. |
| Idempotency | • **9/10** — Repeated executions on unchanged input workbooks yield identical output artifacts and SHA-256 hashes. | • **6/10** — Refresh protects raw input and regenerates derivatives, but the report makes an unverified byte-identical-output claim and no test asserts stable cleaned/report hashes across repeated runs. • **Solution**: Specify artifact-level idempotency semantics and test repeated runs, including hashes where determinism is promised. |

---

## 4. 🛡️ Reliability & Error Handling

| Criteria | 2026-08-12 | 2026-08-12 |
|----------|---------- | ----------|
| Error Rate | • **8/10** — Comprehensive error handling table covering 9 error cases. Guard checks validate path existence, file extensions, and write permissions before processing. | • **6/10** — Core input and collision checks are present, but the error table omits INPUT_NOT_FILE, OUTPUT_PARENT_UNWRITABLE, REPLAY_RAW_INPUT_MISSING, and exceptions from report/script publication. • **Solution**: Complete the error contract and add tests for all documented and emitted failure paths, including unwritable output and replay failures. |
| Error Recoverability | • **9/10** — Staging directory cleanup is guaranteed via try/finally. Atomic publish logic (publish_refresh) maintains backup copies during replacement and rolls back on failure. | • **7/10** — Staging cleanup is reliable and refresh keeps backups, but rollback does not remove newly promoted targets when a later promotion fails and report/script paths are not reopened for validation. • **Solution**: Harden publish_refresh rollback for newly created targets and validate every staged artifact before publication. |
| Retry Success Rate | • **8/10** — Deterministic local operations ensure that retrying after resolving input issues succeeds reliably. | • **4/10** — There is no retry policy or transient-versus-terminal error classification for local I/O failures. • **Solution**: Add bounded retries with backoff only for classified transient filesystem errors; retain immediate failures for validation and integrity errors. |
| Known Bug Recurrence | • **8/10** — Known bugs table documents past issues (replay path extension bug, NoneType on blank headers) with root-cause resolutions. | • **7/10** — Two prior regressions have clear root-cause notes and tests, but current contract drift around conversion/no-imputation has not been recorded as a preventive regression case. • **Solution**: Add the conversion-contract regression to Known Bugs & Resolutions after fixing it and cover it with focused tests. |

---

## 5. 💰 Cost & Scalability

| Criteria | 2026-08-12 | 2026-08-12 |
|----------|---------- | ----------|
| Cost per Execution | • **10/10** — Zero financial cost per execution as no external APIs or cloud services are invoked. | • **10/10** — No paid services or external APIs are used. |
| Scaling Behavior | • **9/10** — Row signature extraction during deduplication now uses batch ws.iter_rows row tuples instead of coordinate cell lookups. • **Solution**: Optimized row signature extraction in row deduplication by using batch row iterators (ws.iter_rows) instead of individual ws.cell(row, col) coordinate lookups. | • **6/10** — openpyxl materializes the workbook; per-cell change logs and one-by-one row deletion can grow poorly on large, duplicate-heavy sheets. • **Solution**: Set supported workbook-size guidance, benchmark large sheets, and rebuild retained rows in one pass instead of repeatedly deleting rows. |
| Unit Test Coverage & Pass Rate | • **9/10** — Test suite runs with pytest or direct python fallback runner seamlessly. • **Solution**: Added standard unittest compatibility / direct execution entry point and pytest fallback mock in test_clean_data_xlsx.py so unit tests run via standard python3 without requiring pytest. | • **7/10** — All 9 tests pass under pytest, covering key happy paths and earlier bugs, but conversion/no-imputation, blank headers, publish rollback, error-code coverage, and repeated-run behavior are untested. • **Solution**: Add tests for conversion opt-in, blank preservation, every error code, refresh rollback, and idempotency; report coverage if a coverage tool is adopted. |
