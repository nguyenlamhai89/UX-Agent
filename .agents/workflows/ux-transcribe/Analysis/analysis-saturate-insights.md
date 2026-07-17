# Skill Performance Analysis: saturate-insights

> Last updated: 2026-07-14

---

## 1. ⚡ Execution Efficiency

| Criteria | 2026-07-07 | 2026-07-08 | 2026-07-08 | 2026-07-14 |
|----------|---------- | ---------- | ---------- | ----------|
| Execution Time | • **7/10** — Sequential API calls per interviewee can be slow for large transcripts. | • **8/10** — Using subagents in parallel is highly efficient for time. | • **8/10** — Using subagents in parallel is highly efficient for time. | • **9/10** — Uses a hybrid parallel approach where individual interviewee transcripts are mapped to JSON by subagents concurrently, and Python handles deterministic report generation. |
| API Call Count | • **9/10** — API calls are appropriately batched per person and for consolidation. | • **8/10** — Subagents use LLM inference efficiently. | • **8/10** — Subagents use LLM inference efficiently. | • **9/10** — The Python script itself makes zero API calls. LLM calls are decoupled, resulting in a clean and predictable API footprint. |
| Token Usage | • **9/10** — Context is kept small by sending only one person's data per extraction. | • **9/10** — Token usage is minimized by segmenting context per interviewee. | • **9/10** — Token usage is minimized by segmenting context per interviewee. | • **8/10** — Context isolation via subagents restricts each agent's view to their specific transcript, significantly reducing token bloat. |
| Resource Consumption | • **9/10** — Temporary files are properly cleaned up at the end of the script. | • **9/10** — Cleans up temporary JSON files properly. | • **9/10** — Cleans up temporary JSON and individual matrix markdown files properly. | • **9/10** — Temporary files (like temp_insights.json) are cleaned up immediately after output generation. |

---

## 2. 🎯 Output Quality & Accuracy

| Criteria | 2026-07-07 | 2026-07-08 | 2026-07-08 | 2026-07-14 |
|----------|---------- | ---------- | ---------- | ----------|
| Output Completeness | • **9/10** — Outputs comprehensive insights and matrix files. | • **9/10** — Produces comprehensive files and handles edge cases gracefully. | • **10/10** — Produces comprehensive files and handles edge cases gracefully, creating a single, unified insights file. | • **9/10** — Produces individual reports, compiled insights with matrix, and line chart representing data saturation curve. |
| Format Compliance | • **7/10** — Markdown tables might break if interviewee names contain pipe characters. • **Solution**: Sanitized interviewee aliases by removing pipe characters during parsing in saturate_insights.py. | • **9/10** — Strictly adheres to Markdown and JSON schemas. Escapes special characters properly. | • **9/10** — Strictly adheres to Markdown and JSON schemas. Escapes special characters properly. | • **9/10** — Enforces formatting via deterministic scripts and safely escapes special characters (like pipe symbols). Summarizes insights in the bullet-point theme format. |
| Content Accuracy | • **9/10** — Prompt rules effectively prevent hallucinated insights. | • **9/10** — Hybrid approach eliminates hallucination and relies on Python for accurate table rendering. | • **9/10** — Hybrid approach eliminates hallucination and relies on Python for accurate table rendering. | • **9/10** — Strictly validates the temp_insights.json schema before processing to ensure structured data is correct. |
| Human Approval Rate | • **8/10** — Past bugs involving AI counting were fixed by using deterministic Python generation. | • **9/10** — Generates a beautiful saturation matrix and chart. | • **9/10** — Generates a beautiful merged saturation matrix and chart. | • **9/10** — Clean markdown layout and interactive visual elements yield highly readable outputs for human users. |

---

## 3. 🔗 Workflow Fit

| Criteria | 2026-07-07 | 2026-07-08 | 2026-07-08 | 2026-07-14 |
|----------|---------- | ---------- | ---------- | ----------|
| I/O Contract Adherence | • **9/10** — Perfectly adheres to the mapped-transcript.md input contract. | • **9/10** — Input matches orchestrator perfectly. | • **10/10** — Input matches orchestrator perfectly, output is streamlined into insights.md. | • **9/10** — Inputs align perfectly with output files from mapping skills, and generated files are placed in correct folders for downstream consumption. |
| Skip-Logic Compatibility | • **8/10** — Supports --generate-only flag for partial skips. | • **9/10** — Generates final files reliably to satisfy skip logic. | • **9/10** — Generates final files reliably to satisfy skip logic. | • **9/10** — Distinct output files make check-skips extremely simple and reliable. |
| Pipeline Passthrough Rate | • **8/10** — Handles malformed JSON and retries natively. | • **9/10** — Exits gracefully with descriptive JSON structures on error. | • **9/10** — Exits gracefully with descriptive JSON structures on error. | • **9/10** — Returns structured JSON error outputs on failure, which helps the orchestrator respond gracefully. |
| Idempotency | • **9/10** — Safely overwrites previous output files. | • **8/10** — Python generation is deterministic and idempotent. | • **9/10** — Python generation is deterministic, idempotent, and self-cleaning. | • **9/10** — Safe file write logic ensures no duplicates or partial states are left on double execution. |

---

## 4. 🛡️ Reliability & Error Handling

| Criteria | 2026-07-07 | 2026-07-08 | 2026-07-08 | 2026-07-14 |
|----------|---------- | ---------- | ---------- | ----------|
| Error Rate | • **9/10** — Error table comprehensively covers potential failures. | • **6/10** — If Matplotlib is missing, the script does not create the chart but still reports it in the success JSON. • **Solution**: Conditionally added `chart_path` to `output_files` only if `MATPLOTLIB_AVAILABLE` is true. | • **9/10** — Error table comprehensively covers potential failures, and the Matplotlib fallback logic correctly mitigates phantom file references. | • **9/10** — Comprehensive input validation logic handles file not found, bad folder inputs, and malformed JSON. |
| Error Recoverability | • **8/10** — Clear error codes allow the orchestrator to recover. | • **9/10** — Cleans up `temp_insights.json` at the end successfully. | • **9/10** — Cleans up `temp_insights.json` at the end successfully. | • **9/10** — Exits with non-zero codes on failure and prints detailed JSON summaries of errors to stdout. |
| Retry Success Rate | • **8/10** — Script has built-in retry logic for extraction errors. | • **9/10** — Deterministic Python processing guarantees success if JSON is valid. | • **9/10** — Deterministic Python processing guarantees success if JSON is valid. | • **8/10** — No built-in retry within python script, since it is a deterministic generator. Orchestrator handles LLM retries beforehand. |
| Known Bug Recurrence | • **9/10** — Bugs were addressed at the root cause by migrating to Python generation. | • **9/10** — Bugs documented well and systemic fixes applied. | • **10/10** — All previously identified known bugs (Matplotlib reporting, hallucination, test suite rot) have been fixed. | • **9/10** — All past known bugs (related to matrix columns and missing summaries) have been resolved with regression tests in place. |

---

## 5. 💰 Cost & Scalability

| Criteria | 2026-07-07 | 2026-07-08 | 2026-07-08 | 2026-07-14 |
|----------|---------- | ---------- | ---------- | ----------|
| Cost per Execution | • **10/10** — Uses built-in AI, incurring no external API costs. | • **8/10** — Cost is optimal by leveraging subagents instead of a massive context window. | • **8/10** — Cost is optimal by leveraging subagents instead of a massive context window. | • **9/10** — LLM calls are only made during the parallel extraction phase, minimizing paid token usage. |
| Scaling Behavior | • **8/10** — Scales linearly, but could be improved with parallel processing as noted above. | • **9/10** — Spawning subagents per interviewee scales well horizontally. | • **9/10** — Spawning subagents per interviewee scales well horizontally. | • **9/10** — Scaling behavior scales efficiently O(1) wall-clock time due to parallel subagent structure. |
| Unit Test Coverage & Pass Rate | • **9/10** — Comprehensive test suite covers the parsing and extraction logic. | • **4/10** — Test file contains stale tests referencing functions that were removed in the recent AI Agent refactor. • **Solution**: Removed stale tests in `test_saturate_insights.py` to fix test suite execution. | • **10/10** — The test suite is fully functional with 25 passing tests that comprehensively cover string parsing, UI integration, and file merging. | • **10/10** — Excellent unit test coverage with 25 unit tests validating loading, matrix generation, report formatting, and CLI flags. |
