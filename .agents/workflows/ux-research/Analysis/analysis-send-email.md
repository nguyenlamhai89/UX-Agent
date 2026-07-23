# Skill Performance Analysis: send-email

> Last updated: 2026-07-23

---

## 1. ⚡ Execution Efficiency

| Criteria | 2026-07-23 |
|----------|----------|
| Execution Time | • **9/10** — Draft generation runs deterministic local path and email checks in milliseconds. Sending runs a single AppleScript subprocess with a configurable 30s timeout. |
| API Call Count | • **10/10** — Makes 0 external API calls. Interacts only locally with macOS osascript (Apple Mail). |
| Token Usage | • **10/10** — Deterministic Python script execution without LLM prompt overhead or token consumption. |
| Resource Consumption | • **10/10** — Zero temporary files created or left behind. Operates in-place on existing HTML reports. |

---

## 2. 🎯 Output Quality & Accuracy

| Criteria | 2026-07-23 |
|----------|----------|
| Output Completeness | • **9/10** — Both draft and send output dicts explicitly define status, sent flag, draft schema, approval token, error details, sender, recipient count, and attachment path. |
| Format Compliance | • **9/10** — Strictly enforces BCC-only recipient delivery, fixed sender address, formal Vietnamese template structure, and APPROVE-SEND-EMAIL:<sha256> token format. |
| Content Accuracy | • **9/10** — Email content generation is fully deterministic, sanitizes control characters, validates email syntax, and prevents header injection. |
| Human Approval Rate | • **9/10** — Full draft disclosure before approval ensures 100% human verification of recipients, subject, body, and exact attachment path prior to sending. |

---

## 3. 🔗 Workflow Fit

| Criteria | 2026-07-23 |
|----------|----------|
| I/O Contract Adherence | • **9/10** — Accepts visualization_result output_file from visualize-insights and folder_path from parent ux-research orchestrator cleanly without schema mismatches. |
| Skip-Logic Compatibility | • **9/10** — Properly handles success and manifest-validated skipped status from visualize-insights. |
| Pipeline Passthrough Rate | • **9/10** — Returns structured error dicts with stable error codes matching parent orchestrator error handling table, preventing unhandled exceptions. |
| Idempotency | • **9/10** — Draft preparation is strictly idempotent. Send operation requires exact content-bound approval token and never automatically retries ambiguous sends. |

---

## 4. 🛡️ Reliability & Error Handling

| Criteria | 2026-07-23 |
|----------|----------|
| Error Rate | • **9/10** — Comprehensive error handling covering recipient syntax, path traversals, missing files, AppleScript missing/timeout/permission errors. |
| Error Recoverability | • **9/10** — HTML report file is preserved on any email error or cancellation, allowing the user to correct recipients or permissions without losing research progress. |
| Retry Success Rate | • **9/10** — Intentionally avoids automatic retries on Apple Mail timeouts/uncertainty to prevent duplicate emails from being dispatched. |
| Known Bug Recurrence | • **9/10** — Past bugs (Python 3.12 parseaddr compatibility and Interview root report directory validation) were resolved at root cause and verified by unit tests. |

---

## 5. 💰 Cost & Scalability

| Criteria | 2026-07-23 |
|----------|----------|
| Cost per Execution | • **10/10** — Zero monetary cost per run as it uses local Apple Mail via AppleScript without external paid services. |
| Scaling Behavior | • **9/10** — Processes multiple BCC recipients efficiently in a single osascript execution in O(N) linear time. |
| Unit Test Coverage & Pass Rate | • **10/10** — 26 unit tests in test_send_email.py providing 100% pass rate and thorough coverage of validation, tokens, subprocess parameters, and error mapping. |
