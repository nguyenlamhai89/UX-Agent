# Send Email Skill Implementation Plan

## 1. Objective and confirmed contract

Create the workflow-owned `send-email` skill at
`.agents/workflows/ux-research/skills/send-email/`.

The skill will:

- Run immediately after `visualize-insights` returns `success` or a valid
  `skipped` result.
- Consume the returned absolute `output_file` unchanged; never reconstruct the
  report path.
- Run immediately after `visualize-insights` returns `success` or a valid
  `skipped` result.
- Consume the returned absolute `output_file` unchanged; never reconstruct the
  report path.
- Ask for recipients at runtime and place every validated address in CC.
- Use deterministic Python helper to generate a formal Vietnamese subject and body.
- Display the complete draft—CC recipients, empty To/BCC, subject, body, and
  HTML attachment path—and pause for explicit approval.
- Send through Gmail SMTP (`smtp.gmail.com:587`) using `GMAIL_APP_USERNAME` and `GMAIL_APP_PASSWORD` passed from parent `.env` only after approval.
- Return structured `awaiting_approval`, `success`, `cancelled`, or `error`
  results.

Implementation is checked against the live
[Antigravity Projects documentation](https://antigravity.google/docs/projects)
and [Skills guide](https://antigravity.google/docs/skills), while retaining the
repository-required workflow-local skill location.

## 2. Files to create

- `.agents/workflows/ux-research/skills/send-email/SKILL.md`
  - Follow every applicable section in `template/skill/SKILL.md`.
  - Document inputs, outputs, approval flow, sequence diagram, stable errors,
    and known-bug policy.
- `.agents/workflows/ux-research/skills/send-email/scripts/send_email.py`
  - Implement deterministic validation, draft normalization, approval
    enforcement, pure-Python Gmail SMTP execution, and structured results.
- `.agents/workflows/ux-research/skills/send-email/tests/test_send_email.py`
  - Add unit tests with smtplib.SMTP execution mocked.

## 3. Files to modify or delete

Modify:

- `.agents/workflows/ux-research/ORCHESTRATOR.md`
  - Add `send-email` after visualization.
  - Document the recipient prompt, complete-draft approval pause, cancellation
    behavior, and output/error contracts.
  - Preserve the HTML report as a successful workflow artifact even if email
    drafting is cancelled or sending fails.
- `.agents/workflows/ux-research/tests/test_e2e_pipeline.py`
  - Extend the pipeline through draft approval and sending.
  - Mock smtplib.SMTP so real emails are never dispatched during tests.

## 4. Implementation details and safety gates

1. Accept the visualization result and require `status` to be `success` or a
   valid `skipped` result.
2. Pass its exact `output_file` into `send-email`; do not derive
   `<project_name>.html`.
3. Validate that the attachment path is absolute, is an existing readable
   regular `.html` file, resolves within
   `<folder_path>/Interview/` or `<folder_path>/Interview/Research Report/`, and matches the visualization
   handoff.
4. Ask for one or more CC recipient addresses at runtime. Strip surrounding
   whitespace, reject empty or malformed addresses and CR/LF header injection,
   deduplicate case-insensitively, and preserve display order.
5. Generate a formal subject and body with instructions to open the HTML report in Chrome, Edge, or Safari. Validate
   both as strings and reject control/header-injection characters in the
   subject.
6. Present one complete draft containing empty To and BCC lists, the validated
   CC list, subject, plain-text body, and exact HTML attachment path.
7. Return or pause with `status: awaiting_approval`. Only an explicit approval
   response or affirmative confirmation keyword may authorize sending.
8. Treat cancellation, ambiguity, missing approval, or an incorrect approval
   token as `cancelled` or `NOT_APPROVED`; do not invoke SMTP.
9. Construct MIME message with `msg["Cc"] = ", ".join(cc_recipients)`. Send using
   pure Python `smtplib.SMTP("smtp.gmail.com", 587)` over STARTTLS.
10. Add a timeout and map authentication failures, connection timeouts, and SMTP exceptions to stable error codes without exposing stack traces.
11. Return `status: success`, `sent: true`, recipient count, and attachment path
    only after successful SMTP completion.

## 5. Tests and validation

Run:

1. `python3 .agents/scripts/check_libraries.py`
2. `python3 -m pytest .agents/workflows/ux-research/skills/send-email/tests -q`
3. `python3 -m pytest .agents/workflows/ux-research/tests/test_e2e_pipeline.py -q`

Unit coverage includes:

- Valid, invalid, duplicate, empty, and header-injection addresses.
- CC construction with empty To and BCC.
- Relative, missing, unreadable, wrong-extension, out-of-report-directory, and
  handoff-mismatched attachments.
- Cancellation, missing approval, and an invalid approval token.
- Missing credentials, timeout, authentication failure, and SMTP error exit.
- Successful approved sending with SMTP mocked.
- Proof that no SMTP call occurs before approval.

The end-to-end test generates the visualization, consumes its returned
`output_file`, exercises the approval gate, and verifies mocked successful sending.

## 6. Assumptions and explicit non-goals

- Pure Python `smtplib` is used with Gmail SMTP (`smtp.gmail.com:587`).
- Parent orchestrator delegates `GMAIL_APP_USERNAME` and `GMAIL_APP_PASSWORD` from `.env`.
- HTML report is attached with MIME type `text/html; charset=utf-8`.
- No retries on SMTP timeouts to prevent duplicate sends.
