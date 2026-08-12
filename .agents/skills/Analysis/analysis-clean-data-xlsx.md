# Skill Performance Analysis: clean-data-xlsx

> Last updated: 2026-08-12

---

## 1. ⚡ Execution Efficiency

| Criteria | 2026-08-12 |
|----------|----------|
| Execution Time | • **7/10** — The skill iterates over worksheet cells multiple times. Specifically, inspect_and_clean performs a full pass over all cells via ws.iter_rows() just to count formulas before starting the main column iteration loop. |
| API Call Count | • **10/10** — Zero external API calls are made. The skill runs entirely in local Python using openpyxl and pandas. |
| Token Usage | • **10/10** — Uses zero LLM tokens; processing is 100% deterministic local Python execution. |
| Resource Consumption | • **8/10** — Creates temporary staging folders via tempfile.mkdtemp and cleans them up reliably in a try/finally block. Memory usage is proportional to workbook size in openpyxl. |

---

## 2. 🎯 Output Quality & Accuracy

| Criteria | 2026-08-12 |
|----------|----------|
| Output Completeness | • **9/10** — Produces a complete set of 5 output artifacts including cleaned workbook, standalone replay script clean.py, bit-identical raw archive, 9-sheet data quality report, and cleaning_log.json. |
| Format Compliance | • **9/10** — Enforces strict output folder hierarchy (<stem>/, Scripts/, Analysis/). Past issue with double file extensions was resolved. |
| Content Accuracy | • **9/10** — Non-destructive cleaning logic preserves formula cells, merged ranges, leading zeros in string identifiers, and un-identifiable headers safely. |
| Human Approval Rate | • **8/10** — High human approval rate due to zero data loss philosophy (flags mixed types/outliers rather than mutating them). Known bugs are documented and fixed. |

---

## 3. 🔗 Workflow Fit

| Criteria | 2026-08-12 |
|----------|----------|
| I/O Contract Adherence | • **9/10** — Input contract accepts standard JSON with input_xlsx_path; output returns structured dictionary containing file paths, hashes, and warnings. |
| Skip-Logic Compatibility | • **9/10** — existing_output_is_valid() validates source SHA-256 against raw archive and log metadata, making skip-logic checks reliable. |
| Pipeline Passthrough Rate | • **8/10** — Properly defines explicit error codes (INPUT_NOT_FOUND, UNSUPPORTED_EXTENSION, INVALID_XLSX, RAW_ARCHIVE_HASH_MISMATCH, etc.) without silent crashes. |
| Idempotency | • **9/10** — Repeated executions on unchanged input workbooks yield identical output artifacts and SHA-256 hashes. |

---

## 4. 🛡️ Reliability & Error Handling

| Criteria | 2026-08-12 |
|----------|----------|
| Error Rate | • **8/10** — Comprehensive error handling table covering 9 error cases. Guard checks validate path existence, file extensions, and write permissions before processing. |
| Error Recoverability | • **9/10** — Staging directory cleanup is guaranteed via try/finally. Atomic publish logic (publish_refresh) maintains backup copies during replacement and rolls back on failure. |
| Retry Success Rate | • **8/10** — Deterministic local operations ensure that retrying after resolving input issues succeeds reliably. |
| Known Bug Recurrence | • **8/10** — Known bugs table documents past issues (replay path extension bug, NoneType on blank headers) with root-cause resolutions. |

---

## 5. 💰 Cost & Scalability

| Criteria | 2026-08-12 |
|----------|----------|
| Cost per Execution | • **10/10** — Zero financial cost per execution as no external APIs or cloud services are invoked. |
| Scaling Behavior | • **7/10** — In row deduplication, signature extraction calls ws.cell(row, col).value cell-by-cell in a loop, which can cause quadratic overhead on large workbooks. |
| Unit Test Coverage & Pass Rate | • **7/10** — Unit test suite in test_clean_data_xlsx.py covers main features, but currently requires pytest to be installed in the runtime environment and fails if run with standard python test tools. |
