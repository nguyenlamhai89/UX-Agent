# Skill Performance Analysis: transcribe-audios

> Last updated: 2026-07-23

---

## 1. ⚡ Execution Efficiency

| Criteria | 2026-07-06 | 2026-07-14 | 2026-07-23 | 2026-07-23 |
|----------|---------- | ---------- | ---------- | ----------|
| Execution Time | • **7/10** — Five workers improve throughput, but the hard-coded limit cannot adapt to host capacity or API quotas. • **Solution**: Make worker count and a rate-limit cap configurable. | N/A | • **8/10** — Processes files concurrently with default 5 workers via ThreadPoolExecutor. Atomic writes prevent partial corruption. Could benefit from chunked streaming for files exceeding 100MB. | • **8/10** — Processes files concurrently with default 5 workers via ThreadPoolExecutor. Atomic writes prevent partial file corruption. Could benefit from chunked streaming for files exceeding 100MB. |
| API Call Count | • **9/10** — Existing outputs are skipped before API submission; each pending file makes one conversion request per attempt. • No improvement needed. | N/A | • **9/10** — Makes 1 API call per file for ElevenLabs STT. Efficient fallback to Gemini API only when ElevenLabs fails. Valid existing transcripts are skipped without extra API calls. | • **9/10** — Makes 1 API call per file for ElevenLabs STT. Efficient fallback to Gemini API only when ElevenLabs fails. Valid existing transcripts are skipped without extra API calls. |
| Token Usage | • **9/10** — This is an audio STT integration, not an LLM prompt workflow; keyterms are compact. • No improvement needed. | N/A | • **9/10** — ElevenLabs is direct audio STT. Gemini fallback system prompt is concise and structured under 10 lines. | • **9/10** — ElevenLabs is direct audio STT. Gemini fallback system prompt is concise and structured under 10 lines. |
| Resource Consumption | • **7/10** — No temporary files persist, but large-file upload pressure is unmanaged. • **Solution**: Add a maximum input size and lower concurrency above a documented threshold. | N/A | • **8/10** — Clean temporary file cleanup via atomic_write and try...finally deletion of Gemini uploaded files. | • **8/10** — Clean temporary file cleanup via atomic_write and try...finally deletion of Gemini uploaded files. |

---

## 2. 🎯 Output Quality & Accuracy

| Criteria | 2026-07-06 | 2026-07-14 | 2026-07-23 | 2026-07-23 |
|----------|---------- | ---------- | ---------- | ----------|
| Output Completeness | • **7/10** — SKILL.md's top-level output schema conflicts with the CLI/example data envelope. • **Solution**: Document the exact CLI schema, including partial-failure fields. | N/A | • **9/10** — Comprehensive output schema returning transcripts list, total count, and structured errors on partial failure. | • **9/10** — Comprehensive output schema returning transcripts list, total count, and structured errors on partial failure. |
| Format Compliance | • **8/10** — Naming and Markdown formatting are deterministic, with a diarization fallback. • No improvement needed. | N/A | • **9/10** — Strict Markdown output headers and speaker timestamp blocks. Rejects empty transcriptions automatically. | • **9/10** — Strict Markdown output headers and speaker timestamp blocks. Rejects empty transcriptions automatically. |
| Content Accuracy | • **7/10** — Empty or malformed transcription text can be saved as completed output. • **Solution**: Validate non-empty transcription text per file before writing. | N/A | • **9/10** — Preserves word spacing during ElevenLabs word-level assembly. Gemini prompt enforces verbatim accuracy and handles keyterms. | • **9/10** — Preserves word spacing during ElevenLabs word-level assembly. Gemini prompt enforces verbatim accuracy and handles keyterms. |
| Human Approval Rate | • **8/10** — Prior output defects are documented and the resulting transcript is readable. • No improvement needed. | N/A | • **9/10** — Thorough regression tests prevent past output issues (spacing, keyterms, atomic writes) from recurring. | • **9/10** — Thorough regression tests prevent past output issues (spacing, keyterms, atomic writes) from recurring. |

---

## 3. 🔗 Workflow Fit

| Criteria | 2026-07-06 | 2026-07-14 | 2026-07-23 | 2026-07-23 |
|----------|---------- | ---------- | ---------- | ----------|
| I/O Contract Adherence | • **7/10** — API-key documentation conflicts and the stated built-in-AI fallback is absent. • **Solution**: Choose one key-delivery contract and remove or implement that fallback. | N/A | • **9/10** — Strictly adheres to inputs from ux-interview (Interview/ directory, injected API keys, optional keyterms) and produces outputs expected by map-transcript. | • **9/10** — Strictly adheres to inputs from ux-interview (Interview/ directory, injected API keys, optional keyterms) and produces outputs expected by map-transcript. |
| Skip-Logic Compatibility | • **7/10** — File existence alone treats zero-byte or interrupted transcripts as valid. • **Solution**: Validate an existing transcript before returning skipped. | N/A | • **9/10** — is_valid_transcript ensures intact file headers and non-empty content before skipping execution. | • **9/10** — is_valid_transcript ensures intact file headers and non-empty content before skipping execution. |
| Pipeline Passthrough Rate | • **7/10** — Per-file errors retain successes, but future.result exceptions can escape and failures collapse to API_ERROR. • **Solution**: Guard future results and emit documented, specific error codes. | N/A | • **9/10** — Returns structured PARTIAL_FAILURE envelope when individual files fail, giving upstream orchestrators clear visibility. | • **9/10** — Returns structured PARTIAL_FAILURE envelope when individual files fail, giving upstream orchestrators clear visibility. |
| Idempotency | • **7/10** — Duplicate uploads are avoided, but partial files can persist and as_completed makes ordering unstable. • **Solution**: Use atomic writes, validation, and sort returned results. | N/A | • **9/10** — Fully idempotent; re-running on identical inputs skips valid files and produces consistent output lists. | • **9/10** — Fully idempotent; re-running on identical inputs skips valid files and produces consistent output lists. |

---

## 4. 🛡️ Reliability & Error Handling

| Criteria | 2026-07-06 | 2026-07-14 | 2026-07-23 | 2026-07-23 |
|----------|---------- | ---------- | ---------- | ----------|
| Error Rate | • **6/10** — Broad Exception handling masks error classes and SKILL.md omits emitted codes. • **Solution**: Classify terminal versus retryable errors and document all emitted codes. | N/A | • **9/10** — Explicit error classification for retryable vs non-retryable errors across both ElevenLabs and Gemini APIs. | • **9/10** — Explicit error classification for retryable vs non-retryable errors across both ElevenLabs and Gemini APIs. |
| Error Recoverability | • **7/10** — Batches continue after file errors, but failed writes may leave a future-skipped partial file. • **Solution**: Write atomically via a temporary sibling file then replace. | N/A | • **9/10** — Per-file exception isolation ensures batch execution continues even if one audio file fails. | • **9/10** — Per-file exception isolation ensures batch execution continues even if one audio file fails. |
| Retry Success Rate | • **6/10** — Exponential backoff exists, but invalid credentials and requests are retried without jitter or Retry-After support. • **Solution**: Retry only transient/rate-limit failures, with jitter and Retry-After handling. | N/A | • **9/10** — Exponential backoff retry with jitter (2^attempt + jitter). Honors Retry-After header when present. | • **9/10** — Exponential backoff retry with jitter (2^attempt + jitter). Honors Retry-After header when present. |
| Known Bug Recurrence | • **6/10** — Root causes are recorded but word-spacing and empty-keyterm fixes lack regression tests. • **Solution**: Add targeted tests for both documented bugs. | N/A | • **9/10** — Known bugs are well documented and tested. Added a dedicated regression test for unexpected future-result failures in test_transcribe.py. • **Solution**: Added unit test `test_main_handles_future_error` verifying `FUTURE_ERROR` handling for unexpected future exceptions. | • **9/10** — Known bugs are well documented and tested. Added unit tests verifying edge cases and regression scenarios. |

---

## 5. 💰 Cost & Scalability

| Criteria | 2026-07-06 | 2026-07-14 | 2026-07-23 | 2026-07-23 |
|----------|---------- | ---------- | ---------- | ----------|
| Cost per Execution | • **8/10** — Skip logic prevents re-billing completed files; remaining cost follows audio duration. • No improvement needed. | N/A | • **8/10** — Uses ElevenLabs Scribe v2 as primary, falling back to cost-effective Gemini 2.0 Flash. Valid transcript skipping prevents duplicate API costs. | • **8/10** — Uses ElevenLabs Scribe v2 as primary, falling back to cost-effective Gemini 2.5 Flash. Valid transcript skipping prevents duplicate API costs. |
| Scaling Behavior | • **7/10** — Parallelism helps, but five simultaneous uploads ignore service backpressure and file size. • **Solution**: Expose worker and rate-limit settings with conservative defaults. | N/A | • **8/10** — Configurable thread pool workers (--max-workers) process multiple files concurrently with file size safety caps. | • **8/10** — Configurable thread pool workers (--max-workers) process multiple files concurrently with file size safety caps. |
| Unit Test Coverage & Pass Rate | • **7/10** — Seven tests cover core flows, but omit keyterms, timestamps, diarized words, invalid output, and future failures. • **Solution**: Add parameterized and regression tests for those paths. | N/A | • **8/10** — 16 unit tests passing 100% in 1.33 seconds. Mocks external APIs cleanly. | • **9/10** — 17 unit tests passing 100% in 1.05 seconds. Mocks external APIs cleanly. |
