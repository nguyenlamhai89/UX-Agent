# Implementation Plan: `clean-data-xlsx`

**Status:** Approved and implemented.  
**Authorization boundary:** User approval was received before implementation. The completed skill, tests, validator result, commits, and pushes follow this plan.

## 1. Confirmed requirements

Create a standalone workspace skill named `clean-data-xlsx` at `.agents/skills/clean-data-xlsx/`.

The skill will:

- Accept exactly one public input: a single existing `.xlsx` file path.
- Never overwrite, modify, rename, or delete the source workbook.
- Create the output directory beside the source workbook using the source filename stem.
- Create a cleaned workbook, immutable raw archive, data-quality report, audit log, and replay script.
- Use deterministic local Python only; no API key, runtime LLM, network request, or external service.
- Process each worksheet independently and never join worksheets.
- Use conservative cleaning defaults:
  - Normalize headers only when safe.
  - Normalize harmless text whitespace.
  - Preserve formulas.
  - Preserve identifiers and leading zeros.
  - Remove only exact duplicate data rows.
  - Do not impute missing values.
  - Do not delete or alter outliers.
  - Flag mixed/ambiguous types, uncertain headers, merged cells, and unsupported/risky workbook structures for review.
- Be atomic, preserve a previous valid output when a later execution fails, clean temporary artifacts, and be idempotent where safe.
- Include the three final skill files only:
  - `.agents/skills/clean-data-xlsx/SKILL.md`
  - `.agents/skills/clean-data-xlsx/scripts/clean_data_xlsx.py`
  - `.agents/skills/clean-data-xlsx/tests/test_clean_data_xlsx.py`
- Initialize the skill through the system `skill-creator` tooling after approval, then conform the result to the workspace `template/skill/SKILL.md`.
- Validate with unit tests and the `skill-creator` quick validator after implementation.
- Stage, commit, and push approved implementation changes to `develop`.

## 2. Scope and non-goals

### In scope

- Deterministic inspection and conservative cleaning of `.xlsx` workbooks.
- Generation of a replayable per-run `clean.py`.
- Auditable reporting and JSON logging.
- Safe handling of multi-sheet workbooks.
- Explicit failure or review flags for unsupported/high-risk workbook features.
- Unit tests for functional behavior, safety guarantees, and output structure.

### Non-goals

- CSV, XLS, XLSM, XLSB, ODS, password-protected, encrypted, or corrupted workbook support.
- Runtime LLM use, API integrations, API-key handling, or `.env` access.
- Semantic data correction, fuzzy duplicate detection, entity matching, deduplication across sheets, or relational joins.
- Missing-value imputation, outlier removal, value coercion based on guesses, or automated repair of ambiguous types.
- Recalculation of formulas by Python; formulas will be preserved as formulas.
- Guaranteed preservation of every Excel-only feature that `openpyxl` cannot safely round-trip.
- Creation of an orchestrator, workflow, workflow E2E test suite, README, changelog, assets, references, installation guide, or other files.

## 3. Exact final file tree

```text
.agents/
└── skills/
    └── clean-data-xlsx/
        ├── SKILL.md
        ├── scripts/
        │   └── clean_data_xlsx.py
        └── tests/
            └── test_clean_data_xlsx.py
```

No other files will be retained in the skill directory.

## 4. Input contract

The skill’s public input is exactly one `.xlsx` file. The implementation will expose an internal Python input dictionary to make invocation and testing explicit:

```python
{
  "input_xlsx_path": "/absolute/or/relative/path/to/source.xlsx"
}
```

Validation rules:

- `input_xlsx_path` is required.
- It must resolve to an existing regular file.
- Its extension must be exactly `.xlsx` case-insensitively.
- It must not point to a directory, symlink escape target outside the resolved file policy, unreadable file, encrypted workbook, or unsupported workbook type.
- No optional cleaning configuration, output path override, sheet selector, API key, merge key, or LLM prompt is accepted.
- The source file’s parent directory must be writable because outputs are created beside it.

The skill will normalize the path to an absolute resolved path before any work begins. The source workbook will only be read; it will never be opened for write.

## 5. Output contract and concrete path example

The implementation will return a structured dictionary:

```python
{
  "status": "success",
  "input_xlsx_path": "/data/Quarterly Sales.xlsx",
  "output_dir": "/data/Quarterly Sales",
  "cleaned_xlsx_path": "/data/Quarterly Sales/Quarterly Sales_cleaned.xlsx",
  "raw_xlsx_path": "/data/Quarterly Sales/Analysis/Quarterly Sales.xlsx",
  "report_xlsx_path": "/data/Quarterly Sales/Analysis/data_quality_report.xlsx",
  "cleaning_log_path": "/data/Quarterly Sales/Analysis/cleaning_log.json",
  "replay_script_path": "/data/Quarterly Sales/Scripts/clean.py",
  "raw_sha256": "<64-character lowercase SHA-256>",
  "cleaned_sha256": "<64-character lowercase SHA-256>",
  "script_sha256": "<64-character lowercase SHA-256>",
  "warnings": [
    {
      "code": "MERGED_CELLS_REVIEW",
      "sheet": "Summary",
      "message": "Merged-cell structures were retained and require review."
    }
  ]
}
```

On failure, it will return or raise a structured error containing a stable error code, human-readable message, source path, and no misleading output paths.

Concrete path resolution example:

```text
Input:
  /Users/alex/Documents/Customer Data.xlsx

<stem>:
  Customer Data

Output tree:
  /Users/alex/Documents/Customer Data/
  ├── Customer Data_cleaned.xlsx
  ├── Scripts/
  │   └── clean.py
  └── Analysis/
      ├── Customer Data.xlsx
      ├── data_quality_report.xlsx
      └── cleaning_log.json
```

The original file `/Users/alex/Documents/Customer Data.xlsx` remains unchanged. The raw archive byte content must exactly match it.

## 6. File-by-file implementation specification

### `.agents/skills/clean-data-xlsx/SKILL.md`

Create concise imperative instructions based strictly on all sections from `template/skill/SKILL.md`, in this exact order:

1. YAML frontmatter containing only:
   - `name: clean-data-xlsx`
   - `description: ...`
2. `## Description`
3. `## Input`
4. `## Output`
5. `## API Key`
6. `## Custom Instructions`
7. `## Sequence Diagram`
8. `## Error Handling & Fallbacks`
9. `## Known Bugs & Resolutions`
10. `## Performance Improvement Solutions`

Required SKILL.md content:

- State that the skill accepts one `.xlsx` path only.
- State that no API key or external API is used.
- Instruct the caller to execute the implementation script with the file path.
- State the exact output-tree contract.
- Instruct the caller to stop and report input errors rather than guessing.
- State safe cleaning limits and review flags.
- State that the per-run replay script is self-contained and runs without an API key.
- Include a concise Mermaid sequence diagram covering validation, immutable raw archive, inspection, cleaning, reporting/logging, atomic publish, and replay.
- Include known-bug entries only if actual bugs are found and fixed during implementation; otherwise state that no known bugs are recorded at initial release.
- Include practical performance guidance without changing deterministic behavior.

### `.agents/skills/clean-data-xlsx/scripts/clean_data_xlsx.py`

Implement the deterministic skill runtime and provide a CLI suitable for skill execution and tests.

Responsibilities:

- Parse exactly one input workbook path.
- Validate source, file format, and output path conditions.
- Inspect and classify workbook structures before writing outputs.
- Create a byte-identical immutable raw archive.
- Perform conservative sheet-by-sheet cleaning.
- Produce the cleaned workbook, report workbook, log JSON, and replay script.
- Use staging directories/files and atomic replacement/publishing.
- Preserve a last known valid output if execution fails.
- Remove temporary staging artifacts in a `finally` path.
- Return/emit stable structured success or error information.
- Avoid importing any model, API client, or secret management library.

The script will include a version constant such as:

```python
SCRIPT_VERSION = "1.0.0"
```

The packaged replay script’s source will be generated deterministically from a single canonical embedded template/versioned cleaning core. The implementation script will calculate its SHA-256 from final UTF-8 bytes before writing the log.

### `.agents/skills/clean-data-xlsx/tests/test_clean_data_xlsx.py`

Implement isolated `pytest` unit tests using temporary test directories under the workspace, for example `.agents/.test-tmp/clean-data-xlsx/`, created per test run and removed during teardown.

Tests will:

- Create minimal fixture workbooks programmatically.
- Invoke the implementation script or import its testable functions.
- Assert paths, workbook contents, hashes, report sheets, log fields, warnings, atomic behavior, and cleanup.
- Avoid external services, installed cloud tools, or API keys.
- Ensure temporary test files remain inside the workspace and are cleaned even after failed assertions where feasible.

## 7. Deterministic cleaning pipeline

### Stage 1: Validate input and preflight output target

1. Resolve `input_xlsx_path`.
2. Validate the `.xlsx` extension and file readability.
3. Compute the stem from the filename without `.xlsx`.
4. Resolve:
   - `<input-parent>/<stem>/`
   - `<input-parent>/<stem>/<stem>_cleaned.xlsx`
   - `<input-parent>/<stem>/Scripts/clean.py`
   - `<input-parent>/<stem>/Analysis/<original-filename>.xlsx`
   - `<input-parent>/<stem>/Analysis/data_quality_report.xlsx`
   - `<input-parent>/<stem>/Analysis/cleaning_log.json`
5. Compute the source SHA-256 before copying.
6. Detect whether the target output directory already exists and apply the rerun/collision policy defined below.
7. Open the workbook with `openpyxl` in a preservation-oriented mode and inspect unsupported/risky structures before any output is published.

### Stage 2: Inspect workbook deterministically

For each worksheet independently:

- Record sheet title, visibility state, dimensions, populated-cell count, and used range.
- Detect tables and defined names where accessible.
- Detect formulas by checking formula cell values rather than evaluated results.
- Detect merged ranges and record them as structural review issues.
- Determine a candidate header row using a deterministic heuristic:
  - Inspect the first non-empty row in the used range.
  - Treat it as a header only if non-empty values are predominantly text-like and unique after safe normalization.
  - Flag `UNCERTAIN_HEADER` rather than modifying when confidence is insufficient, headers are blank/duplicated after normalization, or the sheet is too sparse.
- Identify data rows only below a confirmed header. A sheet without a confirmed header remains unmodified except for workbook-safe preservation and reporting.
- Collect before statistics:
  - row/column counts;
  - missing-value counts by column;
  - exact duplicate row counts;
  - inferred value-kind distribution;
  - mixed-type indicators;
  - outlier indicators for numeric columns;
  - formula, merged-cell, and unsupported-structure flags.

No worksheet is joined to another. The relational merge analysis will be explicitly `not_applicable` because no join key contract is supplied.

### Stage 3: Apply safe deterministic cleaning

For confirmed-header sheets only:

1. Normalize header text conservatively:
   - Convert non-breaking spaces to normal spaces.
   - Collapse repeated internal whitespace.
   - Trim leading/trailing whitespace.
   - Preserve case and meaningful punctuation.
   - Do not alter a header if normalization would produce an empty value or duplicate normalized headers; flag review instead.
2. Normalize harmless whitespace in non-formula string data cells:
   - Replace non-breaking spaces with ordinary spaces.
   - Normalize line-ending variants.
   - Trim leading/trailing whitespace only when the value is not identifier-like.
   - Do not collapse internal spaces in ordinary data values unless they are clearly repeated whitespace and the value is not identifier-like.
3. Protect identifiers and leading zeros:
   - Do not convert string values to numeric types.
   - Do not coerce columns based on inferred types.
   - Treat strings with leading zeros, long digit strings, mixed alphanumeric values, date-like identifiers, and values stored as text as identifier-like unless proven otherwise; retain them byte-for-character except harmless non-breaking-space normalization where safe.
4. Retain formulas:
   - Do not modify formula expressions.
   - Do not remove formula rows as duplicates unless all stored cell values, including formula expressions, are exactly equal and the row is a non-header data row.
5. Remove only exact duplicate data rows:
   - Compare each data row’s normalized comparison representation across the full confirmed data range.
   - Preserve the first occurrence in source order.
   - Remove later occurrences only when every compared cell is exactly equal after the limited allowed normalization.
   - Do not fuzzy match, approximate match, or deduplicate blank/semi-structured rows beyond the exact rule.
6. Do not impute, replace, delete, or otherwise modify missing values.
7. Do not remove, cap, winsorize, or modify outliers.
8. Do not perform type conversion. Flag ambiguous or mixed types for review.

For sheets with merged cells, uncertain headers, unsupported structures, or high-risk features, the implementation will either preserve the sheet unchanged and flag it, or fail before publishing if safe round-tripping cannot be assured.

### Stage 4: Produce cleaned workbook

- Load/copy workbook contents using `openpyxl` with settings intended to preserve formulas and standard formatting where safe.
- Preserve worksheet order, names, visibility, cell styles, number formats, widths, heights, freeze panes, basic tables, and formulas when supported by the library.
- Apply only approved edits.
- Save the cleaned workbook to a staging path, never directly to the final output path.
- Reopen the staged output with `openpyxl` for structural validation.
- Confirm expected worksheet names/order and formula presence match the preflight snapshot where preservation is required.

### Stage 5: Produce report, log, and replay script

- Generate `data_quality_report.xlsx` in staging.
- Generate `cleaning_log.json` in staging.
- Materialize the deterministic packaged `Scripts/clean.py` in staging.
- Calculate SHA-256 values for source/raw copy, cleaned workbook, report, log, and replay script as applicable.
- Add the replay script version and SHA-256 to the log.
- Validate the required output tree and log/report completeness before publish.

### Stage 6: Atomic publish and cleanup

- Publish all staged artifacts as one output set using same-filesystem atomic rename operations where possible.
- Do not replace a valid existing output in a conflict case unless the rerun policy explicitly permits a verified safe refresh.
- On failure, delete only temporary staging artifacts and leave the prior valid output intact.
- Verify the final raw archive SHA-256 equals the original source SHA-256.

## 8. Data-quality report design

Create `<stem>/Analysis/data_quality_report.xlsx` with these worksheets:

| Sheet name | Purpose |
|---|---|
| `Summary` | Run metadata, input/output paths, source/raw hashes, workbook-wide before/after totals, status, warnings, and cleaning totals. |
| `Sheet Statistics` | One row per worksheet with before/after rows, columns, populated cells, removed exact duplicates, normalized headers, normalized text cells, formulas, merged ranges, uncertain-header status, and review status. |
| `Missing Values` | One row per sheet/column with before and after missing counts and percentages. No missing values are changed. |
| `Duplicate Rows` | One row per sheet with candidate exact duplicate count, removed count, preserved-first-occurrence rule, and skipped-deduplication reasons. |
| `Type Issues` | One row per sheet/column for mixed kinds, ambiguous dates/numbers, text-formatted numeric-looking identifiers, leading-zero indicators, and conversion action (`not_converted`). |
| `Outliers` | One row per numeric candidate column with deterministic descriptive statistics and flagged outlier count. Outlier action is always `flagged_not_modified`. |
| `Merge Issues` | Separate merged-cell structure records with sheet, range, and preservation/review status. It will also include a relational-join record per workbook stating `join_analysis: not_applicable`, `reason: no_explicit_key_contract`, and `joins_performed: 0`. |
| `Cleaning Actions` | A row-level or aggregated record of each rule, target sheet/column, count, decision, and rationale. |
| `Warnings` | Stable warning/error-style review records with code, severity, sheet, location, message, and recommended action. |

Report rules:

- Use deterministic ordering: workbook sheet order, then row/column order, then stable lexical ordering where necessary.
- Use standard formats that remain readable in Excel.
- Preserve report formulas only if intentionally used; favor explicitly written values for auditability.
- Do not expose source cell values unnecessarily in the report when counts and locations are sufficient.
- Record outliers using a documented deterministic method, such as IQR for numeric columns with enough valid numeric values; do not label columns as outlier-free when there is insufficient data.

## 9. Cleaning-log design

Create `<stem>/Analysis/cleaning_log.json` as UTF-8 JSON with stable key ordering and deterministic list ordering.

Top-level structure:

```json
{
  "schema_version": "1.0",
  "status": "success",
  "run": {},
  "input": {},
  "output": {},
  "packaged_replay_script": {},
  "workbook_inspection": {},
  "rules": [],
  "changes": [],
  "quality_findings": {},
  "validation": {},
  "warnings": [],
  "errors": []
}
```

Required fields:

### `run`

- `tool_name`
- `tool_version`
- deterministic execution metadata, excluding nondeterministic timestamps unless explicitly labeled as informational
- `python_version`
- `library_versions`
- `platform` only if needed for diagnostics

### `input`

- `source_path`
- `source_filename`
- `source_sha256`
- `source_size_bytes`
- `raw_archive_path`
- `raw_archive_sha256`
- `raw_archive_verified: true`

### `output`

- `output_dir`
- `cleaned_xlsx_path`
- `cleaned_xlsx_sha256`
- `report_xlsx_path`
- `report_xlsx_sha256`
- output-tree version/format identifier

### `packaged_replay_script`

- `path`
- `script_version`
- `sha256`
- `encoding: "utf-8"`
- `entrypoint`
- `raw_input_resolution: "../Analysis/<original-filename>.xlsx"`
- `replay_output_behavior`
- `api_key_required: false`

### `workbook_inspection`

- workbook-level findings
- worksheets in source order
- worksheet dimensions
- header-detection result
- formula counts
- merged-range details
- risky/unsupported feature findings
- relational merge analysis:
  - `status: "not_applicable"`
  - `reason: "no_explicit_key_contract"`
  - `joins_performed: 0`

### `rules`

A complete rule catalog containing deterministic rule IDs, descriptions, applicability, and whether each rule may alter content. Examples:

- `HEADER_WHITESPACE_NORMALIZATION`
- `DATA_WHITESPACE_NORMALIZATION`
- `IDENTIFIER_PRESERVATION`
- `FORMULA_PRESERVATION`
- `EXACT_DUPLICATE_ROW_REMOVAL`
- `MISSING_VALUE_NO_IMPUTATION`
- `OUTLIER_FLAG_ONLY`
- `TYPE_CONVERSION_DISABLED`
- `NO_CROSS_SHEET_JOIN`

### `changes`

- Aggregated and, where needed, location-specific change records.
- Include sheet, cell/range or row identifiers, original and resulting values only when safe and needed for auditability, rule ID, and rationale.
- Include exact duplicate row removals with retained row and removed row references.
- Record zero-count rules as evaluated but no-op where useful for reruns.

### `quality_findings`

- missing-value, duplicate, type-issue, outlier, merged-cell, uncertain-header, and unsupported-feature summaries.
- All review-only decisions must clearly state that no automated alteration was made.

### `validation`

- staging checks completed
- cleaned workbook reopen result
- worksheet/order checks
- formula-preservation checks
- raw SHA-256 verification
- report/log/replay presence checks
- atomic publish result

### `warnings` and `errors`

- Records containing stable code, severity, message, sheet/location when applicable, and fallback decision.

The log must contain every rule evaluated and all changes needed to audit a run or replay the same cleaning behavior.

## 10. Per-run replay artifact design

The skill implementation script and packaged replay script are distinct:

| Artifact | Location | Role |
|---|---|---|
| Skill implementation | `.agents/skills/clean-data-xlsx/scripts/clean_data_xlsx.py` | Executes the skill from the original user-selected `.xlsx` and constructs the full output tree. |
| Replay artifact | `<input-parent>/<stem>/Scripts/clean.py` | Self-contained deterministic snapshot for that completed run; reruns cleaning from the immutable raw archive without an API key. |

`clean.py` materialization policy:

- Generate `clean.py` from a canonical versioned source template embedded in the implementation script or deterministically derived from the same cleaning-core source.
- Include all imports, cleaning rules, report/log helpers necessary for replay.
- Do not import `.agents` files or depend on the original skill directory.
- Write the final script as UTF-8 with normalized newline convention.
- Calculate SHA-256 from exact written bytes and record it in `cleaning_log.json`.
- Include a `SCRIPT_VERSION` matching the snapshot implementation version.
- Include a clearly defined CLI with no API-key argument.

Replay input resolution:

```text
<stem>/Scripts/clean.py
  └── resolves its own directory
      └── ../Analysis/<original-filename>.xlsx
```

The original filename will be embedded safely in the replay script and confirmed against the log’s archived raw hash before replay cleaning begins.

Replay output behavior:

- Replay must not recursively create `<input-parent>/<stem>/<stem>/...`.
- Replay treats the existing parent output tree as the run root.
- It reads only `../Analysis/<original-filename>.xlsx`.
- It writes replay results to a controlled staging directory inside the existing run root, then atomically refreshes only replayable derivative artifacts:
  - `<stem>_cleaned.xlsx`
  - `Analysis/data_quality_report.xlsx`
  - `Analysis/cleaning_log.json`
- It must never overwrite `Analysis/<original-filename>.xlsx`.
- It must verify the raw archive SHA-256 before use.
- It will record replay mode and prior/new derivative hashes in the refreshed log.
- If the raw archive does not match the expected hash, replay fails with `RAW_ARCHIVE_HASH_MISMATCH` and leaves current derivatives untouched.

## 11. Safety, raw preservation, atomicity, and rerun policy

### Source and raw preservation

- Read the source XLSX without write access.
- Copy the source to `Analysis/<original-filename>.xlsx` using a byte-level copy operation.
- Compute SHA-256 on the source before copy and on the archive after copy.
- Require exact hash equality before continuing to final publish.
- Never open the raw archive in write mode.
- Record the verified hash in `cleaning_log.json`.

### Atomicity

- Build all artifacts under a uniquely named staging directory located inside the source parent/output parent so atomic renames stay on the same filesystem.
- Validate all staged artifacts before final publication.
- Publish only after successful validation.
- Preserve the last valid output if any stage fails.
- In cleanup, remove only the exact staging directory created by the current run.
- Never remove or recursively clean the source parent, workspace root, or existing final output directory.

### Existing output folder and collision policy

1. If `<input-parent>/<stem>/` does not exist:
   - Create and publish a new output tree.

2. If the output directory exists and contains a valid prior output:
   - Read `Analysis/cleaning_log.json`.
   - Verify that:
     - the archived raw filename matches the current source filename;
     - the archived raw SHA-256 equals the current source SHA-256;
     - the archive file exists and its actual SHA-256 matches;
     - required derivative artifacts exist.
   - If all checks pass, permit a safe idempotent refresh using staging and atomic replacement of derivatives while retaining the immutable archive.
   - If generated artifacts would be byte-identical, no unnecessary replacement is required.

3. If the output directory exists but raw archive/hash differs from the current source:
   - Fail with `OUTPUT_COLLISION_RAW_MISMATCH`.
   - Do not overwrite anything.
   - Require the user to rename/move the conflicting output directory or provide a differently named source workbook.

4. If the output directory exists but is incomplete, invalid, or missing the log/raw archive:
   - Fail with `OUTPUT_COLLISION_INVALID_STATE`.
   - Preserve existing contents.
   - Require user review rather than attempting a destructive repair.

### Idempotence

Given identical source bytes, library behavior, and script version, repeated runs will apply the same rules in the same order and produce equivalent logical outputs. The log may contain explicitly identified run metadata, but cleaning decisions, hashes of deterministic content, and report ordering will remain stable where library serialization permits.

## 12. Errors and fallbacks

Define stable error codes and use them consistently in CLI output, exceptions, logs when a log can safely be produced, and test assertions.

| Code | Condition | Fallback behavior |
|---|---|---|
| `INPUT_PATH_REQUIRED` | No path supplied. | Stop; request one `.xlsx` file path. |
| `INPUT_NOT_FOUND` | Source path does not exist. | Stop; report resolved path. |
| `INPUT_NOT_FILE` | Path is a directory or unsuitable file type. | Stop; request a regular `.xlsx` file. |
| `UNSUPPORTED_EXTENSION` | Input is not `.xlsx`. | Stop; request a supported `.xlsx` workbook. |
| `INPUT_UNREADABLE` | File cannot be read. | Stop; report permission/readability issue. |
| `INVALID_XLSX` | Workbook cannot be parsed as a valid XLSX. | Stop; preserve all existing outputs. |
| `ENCRYPTED_OR_PROTECTED_WORKBOOK` | Encrypted/password-protected workbook cannot be safely processed. | Stop; request an unlocked `.xlsx` copy. |
| `OUTPUT_PARENT_UNWRITABLE` | Source parent cannot receive output. | Stop; request a writable location. |
| `OUTPUT_COLLISION_RAW_MISMATCH` | Existing output belongs to different source bytes. | Stop; do not overwrite. |
| `OUTPUT_COLLISION_INVALID_STATE` | Existing output tree is incomplete/corrupt/unverifiable. | Stop; preserve it for review. |
| `RAW_ARCHIVE_COPY_FAILED` | Raw copy cannot be created or verified. | Stop; remove staging only. |
| `RAW_ARCHIVE_HASH_MISMATCH` | Raw archive bytes differ from source or expected log hash. | Stop; do not publish/refresh derivatives. |
| `UNSUPPORTED_WORKBOOK_FEATURE` | A feature cannot be safely round-tripped. | Fail before publish or preserve unchanged only when safety is confirmed; always flag. |
| `RISKY_WORKBOOK_FEATURE` | Feature may be preserved but requires review. | Continue only if safe preservation is verified; emit warning. |
| `UNCERTAIN_HEADER` | Header cannot be confidently identified. | Do not normalize/deduplicate that sheet; report warning. |
| `REPORT_GENERATION_FAILED` | Report cannot be generated. | Stop; do not publish partial output. |
| `LOG_GENERATION_FAILED` | Log cannot be generated. | Stop; do not publish partial output. |
| `POST_WRITE_VALIDATION_FAILED` | Staged workbook/output validation fails. | Stop; remove staging only. |
| `ATOMIC_PUBLISH_FAILED` | Final rename/replace fails. | Preserve last valid output; remove only staging where possible. |
| `REPLAY_RAW_INPUT_MISSING` | Packaged replay cannot find expected raw archive. | Stop; preserve existing derivatives. |
| `INTERNAL_ERROR` | Unexpected implementation error. | Emit sanitized diagnostics; preserve source and existing output. |

Warnings will use distinct review-oriented codes, including:

- `MERGED_CELLS_REVIEW`
- `FORMULAS_PRESERVED`
- `IDENTIFIER_PRESERVED`
- `MIXED_TYPES_REVIEW`
- `OUTLIERS_FLAGGED_NOT_MODIFIED`
- `MISSING_VALUES_NOT_IMPUTED`
- `NO_CROSS_SHEET_JOIN`
- `UNCERTAIN_HEADER`
- `UNSUPPORTED_FEATURE_REVIEW`

## 13. Dependency plan

Use local deterministic Python dependencies only:

- `openpyxl`
  - Read/write `.xlsx`.
  - Preserve formulas with `data_only=False`.
  - Inspect sheets, merged cells, tables, styles, dimensions, and formulas.
  - Generate `data_quality_report.xlsx`.

- `pandas`
  - Perform deterministic tabular profiling where useful.
  - Compute missing-value counts, exact duplicate candidates, type distributions, and numeric outlier summaries.
  - Avoid pandas round-tripping as the primary workbook writer when it could lose workbook features; apply edits through `openpyxl`.

- Python standard library:
  - `argparse`, `copy`, `csv` only if needed internally, `dataclasses`, `datetime` only for informational metadata, `hashlib`, `json`, `os`, `pathlib`, `re`, `shutil`, `sys`, `tempfile` only with workspace/source-parent-scoped staging, `traceback`, `uuid`.

- `pytest`
  - Unit test execution.

Before implementation execution, run the workspace dependency check:

```text
python3 .agents/scripts/check_libraries.py
```

The check may warn about missing/outdated libraries but will not install or upgrade dependencies automatically. If an immediately required library is unavailable, implementation validation will report the dependency blocker rather than silently substituting unsafe behavior.

## 14. Detailed unit-test matrix

| Test area | Scenario | Expected assertions |
|---|---|---|
| Output layout | Single `input.xlsx`. | Creates exactly `<stem>_cleaned.xlsx`, `Scripts/clean.py`, and required `Analysis/` artifacts at required sibling paths. |
| Source immutability | Record source bytes/hash before run. | Source bytes/hash are unchanged after success and failure paths. |
| Raw archive fidelity | Run on a known workbook. | `Analysis/<original-filename>.xlsx` has the same bytes and SHA-256 as source. |
| Multiple worksheets | Workbook with several sheets. | Sheet order/names retained; each sheet inspected and reported independently; no join occurs. |
| Header normalization | Safe text headers with outer/repeated whitespace/NBSP. | Headers normalize only as specified; action/log/report counts are correct. |
| Uncertain headers | Blank, duplicate, numeric-only, or sparse first row. | Sheet is not header-cleaned/deduplicated; `UNCERTAIN_HEADER` is reported. |
| Data whitespace normalization | Safe plain-text cells. | Harmless whitespace normalization applies and is logged. |
| Identifier protection | Leading-zero strings, long numbers as text, alphanumeric IDs. | Values remain strings and retain leading zeros; no numeric coercion. |
| Exact duplicates | Identical non-header data rows. | First row retained, later exact rows removed, removal count/locations logged. |
| Near duplicates | Case, punctuation, spacing, or one-cell differences. | Not removed unless resulting rows are exactly equal under permitted normalization. |
| Missing values | Empty cells/rows. | Missing statistics reported; no imputation or deletion occurs. |
| Mixed types | Column containing text, number, and date-like values. | Values remain unchanged; mixed-type warning/report entry is present. |
| Outliers | Numeric data with a clear extreme value. | Outlier is reported deterministically and remains unchanged. |
| Formula preservation | Formula cells and formula-containing rows. | Formula expressions remain formulas; formulas are not recalculated/coerced. |
| Merged cells | Worksheets containing merged ranges. | Merges are recorded in `Merge Issues`; structures are preserved if safe or run fails before publish if unsafe. |
| No cross-sheet join | Two sheets with possible matching IDs. | Log/report state `not_applicable`; no joins or cross-sheet modifications occur. |
| Report contents | Successful run. | Required report sheets, required columns/rows, summary values, warnings, and merge status exist. |
| Log completeness | Successful run. | Required top-level JSON structure, hashes, rules, changes, validation, replay script version/SHA-256, and no-API declaration exist. |
| Replay script | Execute packaged `clean.py` without API key. | It resolves `../Analysis/<original>.xlsx`, verifies raw hash, refreshes derivatives safely, and does not create nested output tree. |
| Existing valid rerun | Rerun with same source bytes. | Raw archive remains unchanged; output refresh is safe/idempotent; no collision failure. |
| Raw mismatch conflict | Existing output generated from different bytes under same stem. | Fails with `OUTPUT_COLLISION_RAW_MISMATCH`; existing artifacts remain unchanged. |
| Invalid existing output | Existing output missing log/raw archive. | Fails with `OUTPUT_COLLISION_INVALID_STATE`; does not repair/destructively overwrite. |
| Invalid files | Missing, non-XLSX, directory, malformed XLSX. | Stable error code; no final output tree or partial artifacts published. |
| Unsupported/risky structures | Fixture representing unsupported/risky features where detectable. | Safe failure or explicit warning/preservation behavior; never silent corruption. |
| Atomic failure behavior | Force report/write/validation/publish failure using mocks. | Staging is cleaned, source and prior valid outputs remain intact, no partial new final output. |
| Temporary cleanup | Success and failure runs. | Current-run staging/test artifacts are removed; test artifacts remain only inside workspace during execution. |
| CLI contract | Zero, one, and too-many arguments. | Exactly one `.xlsx` argument is required; stable error behavior. |
| Determinism | Same fixture executed twice under same environment. | Equivalent cleaning decisions, stable rule ordering, raw hash equality, and expected output semantics. |

## 15. Validation and acceptance criteria

After implementation approval:

1. Run the dependency check:

   ```text
   python3 .agents/scripts/check_libraries.py
   ```

2. Initialize the skill with the system `skill-creator` tooling.

3. Conform the generated structure to the workspace-required three-file tree and `template/skill/SKILL.md`.

4. Run the unit test suite:

   ```text
   pytest .agents/skills/clean-data-xlsx/tests/test_clean_data_xlsx.py
   ```

5. Run the `skill-creator` quick validator against `.agents/skills/clean-data-xlsx/`.

6. Confirm no temporary test outputs remain outside the designated workspace-local test location.

7. Inspect the final directory tree to confirm only the three authorized skill files remain.

8. Verify acceptance using a representative workbook:
   - source hash is unchanged;
   - raw archive hash equals source hash;
   - cleaned workbook exists in the correct location;
   - report contains all required sheets;
   - log includes all required audit/replay metadata;
   - packaged `clean.py` runs without an API key and uses the raw archive;
   - no nested output tree is created;
   - formulas, identifiers, missing values, and outliers follow the stated preservation rules.

9. If all checks pass, stage, commit, and push to `develop`:

   ```text
   git add .
   git commit -m "update: add clean-data-xlsx skill"
   git push origin develop
   ```

## 16. Ordered execution steps after approval

1. Re-read `template/skill/SKILL.md` completely and inspect any relevant workspace conventions.
2. Run `python3 .agents/scripts/check_libraries.py` and report non-blocking dependency warnings.
3. Initialize `clean-data-xlsx` using the system `skill-creator` tooling.
4. Remove any generated nonessential files so the final skill tree contains only the three authorized files.
5. Create concise `SKILL.md` with exactly the required workspace-template sections and frontmatter restriction.
6. Implement `scripts/clean_data_xlsx.py` with:
   - input/output contracts;
   - preflight validation;
   - deterministic inspection;
   - conservative cleaning;
   - immutable raw archival/hash verification;
   - report/log/replay generation;
   - atomic publication;
   - cleanup;
   - stable errors and CLI.
7. Implement `tests/test_clean_data_xlsx.py` covering the complete test matrix.
8. Run the unit tests and fix any implementation defects.
9. When an actual bug is fixed, document the bug and resolution in `SKILL.md` and add regression coverage.
10. Run the `skill-creator` quick validator and correct validation issues.
11. Re-run the full unit suite after all changes.
12. Verify the final skill contains only the three authorized files and no leftover temporary test artifacts.
13. Stage, commit, and push the approved implementation to `develop`.

## 17. Explicit approval gate

Approval was received; the skill has been created, validated, committed, and pushed according to this plan.
