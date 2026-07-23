# Skill Performance Analysis: extract-map

> Last updated: 2026-07-23

---

## 1. ⚡ Execution Efficiency

| Criteria | 2026-07-16 | 2026-07-16 | 2026-07-23 |
|----------|---------- | ---------- | ----------|
| Execution Time | • **4/10** — The script loops through extracted-*.md files and calls the Antigravity AI agent once per file. This results in 5 separate sequential LLM API calls, which is slow and inefficient. • **Solution**: Refactored the script to read all phase files first and execute a single consolidated LLM API call, updating all map stages in one pass. | • **10/10** — The skill runs locally and programmatically in Python, resulting in near-instantaneous execution without any network or AI overhead. | • **10/10** — Runs locally and programmatically in Python, resulting in near-instantaneous execution without any network or AI overhead. |
| API Call Count | • **5/10** — Makes 5 separate sequential external API calls to the LLM agent, one for each phase. This increases risk of rate limits and network latency. • **Solution**: Consolidated the logic to use exactly one LLM call containing all phase data. | • **10/10** — Deterministic local script that performs 0 external API calls. | • **10/10** — Deterministic local script that performs 0 external API calls. |
| Token Usage | • **6/10** — The current prompt sends the entire current journey-map.md repeatedly back and forth in each iteration. For 5 phases, the accumulating journey map is sent 5 times, resulting in redundant input tokens. • **Solution**: Transitioned to a single consolidated call, eliminating repetitive prompt context transmissions. | • **10/10** — Does not use LLMs, resulting in 0 token usage. | • **10/10** — Does not use LLMs, resulting in 0 token usage. |
| Resource Consumption | • **9/10** — Reads files and updates them locally. Handles memory and file handles correctly. | • **7/10** — The script uses synchronous filesystem methods (glob, open) within the async function `extract_map`, which blocks the asyncio event loop. • **Solution**: Implemented non-blocking filesystem calls by wrapping synchronous operations in `asyncio.to_thread`. | • **9/10** — Uses asyncio.to_thread for non-blocking file reads/writes/globs; clean memory and file handle management. |

---

## 2. 🎯 Output Quality & Accuracy

| Criteria | 2026-07-16 | 2026-07-16 | 2026-07-23 |
|----------|---------- | ---------- | ----------|
| Output Completeness | • **8/10** — Correctly maps extracted phases into a single journey-map.md. However, since it processes files in alphabetical/glob order, it relies on the AI to correctly map columns. If a phase is missing or processed out of order, it can cause layout issues. | • **7/10** — Silent tolerance of missing phase files; if some stages are missing `interpret-*.md` files, the script proceeds and outputs empty columns without warning or error. • **Solution**: Added logic to verify all standard phases are present and check for empty cells, returning warnings in the response if found. | • **9/10** — Parses all interpret-*.md files across 5 standard stages. Validates missing stages and empty fields with clear warnings. |
| Format Compliance | • **8/10** — Enforces markdown table format and extracts code blocks correctly. | • **6/10** — The cell values are not sanitized. If the input text contains raw newlines (`\n`) or unescaped pipe characters (` | `), it will completely break the final generated Markdown table structure. • **Solution**: Added a sanitization function to replace newlines with `<br>` and escape pipe characters (`\ | `) to protect markdown table integrity. | • **9/10** — Enforces standard Customer Journey Map table schema; sanitizes cell values against pipes and newlines. |
| Content Accuracy | • **8/10** — Preserves text from columns. Uses HTML <br> tags to keep table formatting intact. | • **8/10** — Programmatic extraction guarantees zero AI hallucinations. Substring matching of category keys works but could be made more robust against minor variations. | • **9/10** — Deterministic extraction ensures 100% content fidelity with zero AI hallucination. |
| Human Approval Rate | • **8/10** — Output is generally clean, though sequential generation carries a slight risk that earlier edits get overwritten or formatting breaks during subsequent iterations. | • **9/10** — Deterministic logic ensures high quality and low rejection rate, provided the input format is correct. | • **9/10** — Generates highly accurate, well-formatted markdown tables ready for user review. |

---

## 3. 🔗 Workflow Fit

| Criteria | 2026-07-16 | 2026-07-16 | 2026-07-23 |
|----------|---------- | ---------- | ----------|
| I/O Contract Adherence | • **10/10** — Adheres exactly to input folder_path and outputs journey-map.md in Journey Map folder. | • **10/10** — Properly resolves `folder_path` whether pointing to project root or the nested `Journey Map` folder. | • **10/10** — Fully compliant with folder_path inputs and outputs journey-map.md in Journey Map subdirectory. |
| Skip-Logic Compatibility | • **9/10** — Clear, deterministic output filenames make it perfectly compatible with orchestrator skip-logic. | • **6/10** — Skip logic only checks for placeholder strings; if source files (`interpret-*.md`) are updated, the script still skips execution instead of regenerating the map. • **Solution**: Upgraded idempotency skip logic to compare the generated output with the existing file content, ensuring updates to source files are always correctly compiled. | • **9/10** — Checks if destination file exists and is identical to compiled output to avoid unnecessary rewrites. |
| Pipeline Passthrough Rate | • **9/10** — Gracefully catches exceptions per phase, returns error statuses, and exits with non-zero exit code if error occurs. | • **8/10** — It catches exceptions per file and continues, preventing a complete pipeline halt, but doesn't pass parsing warning details back to the orchestrator. | • **9/10** — Catches exceptions per file and returns structured status dicts to prevent pipeline crashes. |
| Idempotency | • **7/10** — Overwrites journey-map.md. However, if the mapping script is run twice, it re-runs all LLM calls, which is expensive and not cached. • **Solution**: Implemented a checklist check that detects completed maps and skips AI calls entirely when appropriate. | • **10/10** — Deterministic; running twice on same input always yields identical files. | • **10/10** — Running multiple times with unchanged source files produces identical output and skips processing. |

---

## 4. 🛡️ Reliability & Error Handling

| Criteria | 2026-07-16 | 2026-07-16 | 2026-07-23 |
|----------|---------- | ---------- | ----------|
| Error Rate | • **8/10** — Uses robust error catching for each phase, printing errors to stderr. | • **7/10** — Lacks exception handling around the final file write operations, which could cause unhandled crashes on OS/Permission errors. • **Solution**: Wrapped the file writing step in a try-except block to safely catch filesystem errors and return structured error responses. | • **9/10** — Catches missing directories, unparseable files, missing input files, and filesystem permission errors. |
| Error Recoverability | • **8/10** — Exits immediately and returns an error dict, letting the orchestrator handle the error. | • **9/10** — Only writes to `journey-map.md` at the very end of execution, ensuring no partial or corrupted output is left on crash. | • **9/10** — Atomic operation writes to journey-map.md only upon successful table assembly. |
| Retry Success Rate | • **7/10** — No retry mechanism is built in for individual AI calls, which are prone to transient network or API errors. • **Solution**: Added retry mechanism with exponential backoff for up to 3 attempts on LLM agent chat calls. | • **10/10** — Local offline script; retries are not applicable or needed. | • **10/10** — Local execution script, retries are not required or applicable. |
| Known Bug Recurrence | • **10/10** — No known recurring bugs. | • **10/10** — No documented bugs or recurring failures. | • **10/10** — No known recurring bugs. |

---

## 5. 💰 Cost & Scalability

| Criteria | 2026-07-16 | 2026-07-16 | 2026-07-23 |
|----------|---------- | ---------- | ----------|
| Cost per Execution | • **5/10** — Calls the paid LLM API 5 times sequentially, passing redundant context each time. This makes the skill unnecessarily expensive. • **Solution**: Batched all phases into a single call, slashing API consumption costs. | • **10/10** — Local execution has zero API cost. | • **10/10** — $0 cost per execution. |
| Scaling Behavior | • **5/10** — Scalability is poor because adding more phases scales the number of API calls and token count quadratically/linearly. • **Solution**: Refactored to map all phases concurrently in a single LLM invocation. | • **9/10** — Scaling is bounded by the fixed 5 stages of the customer journey map, so performance remains highly scalable. | • **9/10** — Executes in milliseconds; bounded by 5 customer journey stages. |
| Unit Test Coverage & Pass Rate | • **8/10** — The unit tests mock the google.antigravity module and filesystem nicely, ensuring that collection does not fail. However, it only tests with a single mock phase file and does not cover loop failures or malformed responses. | • **7/10** — Unit tests pass and mock dependencies, but they only test basic success/failure paths and lack coverage for edge cases like malformed markdown tables. • **Solution**: Expanded the unit test suite to cover cell sanitization, file writing errors, and correct idempotency handling. | • **9/10** — Complete unit test coverage (6 tests) covering happy path, missing dir, idempotency, direct path, sanitization, and filesystem write errors. |
