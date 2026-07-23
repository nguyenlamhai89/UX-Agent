# Send Email Skill Implementation Plan

## 1. Objective and confirmed contract

Create the workflow-owned `send-email` skill at
`.agents/workflows/ux-research/skills/send-email/`.

The skill will:

- Run immediately after `visualize-insights` returns `success` or a valid
  `skipped` result.
- Consume the returned absolute `output_file` unchanged; never reconstruct the
  report path.
- Ask for recipients at runtime and place every validated address in BCC only.
- Use built-in AI to suggest a subject and plain-text body.
- Display the complete draft—BCC recipients, empty To/CC, subject, body, and
  HTML attachment path—and pause for explicit approval.
- Send through Apple Mail only after approval.
- Return structured `awaiting_approval`, `success`, `cancelled`, or `error`
  results.
- Use no email API, external LLM API, API key, or new package dependency.

Implementation will be checked against the live
[Antigravity Projects documentation](https://antigravity.google/docs/projects)
and [Skills guide](https://antigravity.google/docs/skills), while retaining the
repository-required workflow-local skill location.

## 2. Files to create

- `.agents/workflows/ux-research/skills/send-email/SKILL.md`
  - Follow every applicable section in `template/skill/SKILL.md`.
  - Omit the API Key section entirely.
  - Document inputs, outputs, approval flow, sequence diagram, stable errors,
    and known-bug policy.
- `.agents/workflows/ux-research/skills/send-email/scripts/send_email.py`
  - Implement deterministic validation, draft normalization, approval
    enforcement, static AppleScript execution, and structured results.
- `.agents/workflows/ux-research/skills/send-email/tests/test_send_email.py`
  - Add unit tests with all subprocess execution mocked.
- `.agents/scratch/create_send_email_skill.py`
  - Create a temporary workspace-local driver that invokes built-in AI during
    the implementation phase, as required by the repository rules.

## 3. Files to modify or delete

Modify:

- `.agents/workflows/ux-research/ORCHESTRATOR.md`
  - Add `send-email` after visualization.
  - Document the recipient prompt, complete-draft approval pause, cancellation
    behavior, and output/error contracts.
  - Preserve the HTML report as a successful workflow artifact even if email
    drafting is cancelled or Apple Mail fails.
- `.agents/workflows/ux-research/tests/test_e2e_pipeline.py`
  - Extend the pipeline through draft approval and sending.
  - Mock the sender boundary so `osascript` and Apple Mail can never execute
    during tests.
- `.agents/workflows/ux-research/skills/README.md`
  - Delete the empty-directory placeholder after the first workflow-owned skill
    is created.

Delete after implementation:

- `.agents/scratch/create_send_email_skill.py`
  - Remove the temporary creation driver after generated files are reviewed and
    validated.

No existing production files will otherwise be deleted.

## 4. Implementation details and safety gates

1. Accept the visualization result and require `status` to be `success` or a
   valid `skipped` result.
2. Pass its exact `output_file` into `send-email`; do not derive
   `<project_name>.html`.
3. Validate that the attachment path is absolute, is an existing readable
   regular `.html` file, resolves within
   `<folder_path>/Interview/Research Report/`, and matches the visualization
   handoff.
4. Ask for one or more recipient addresses at runtime. Strip surrounding
   whitespace, reject empty or malformed addresses and CR/LF header injection,
   deduplicate case-insensitively, and preserve display order.
5. Use built-in AI to propose a concise subject and plain-text body. Validate
   both as strings and reject control/header-injection characters in the
   subject.
6. Present one complete draft containing empty To and CC lists, the validated
   BCC list, subject, plain-text body, and exact HTML attachment path.
7. Return or pause with `status: awaiting_approval`. Only an explicit approval
   response may produce the sender's exact approval token or flag.
8. Treat cancellation, ambiguity, missing approval, or an incorrect approval
   token as `cancelled` or `NOT_APPROVED`; do not invoke a subprocess.
9. Keep AppleScript source static. Pass recipients, subject, body, and attachment
   path only through `osascript` argument vectors using
   `subprocess.run([...], shell=False)`; never interpolate user-controlled values
   into AppleScript source.
10. Construct only Apple Mail `bcc recipient` objects. Never create To or CC
    recipients.
11. Add a timeout, capture stderr safely, and map missing `osascript`, Apple Mail
    automation denial, timeout, non-zero exit, and unexpected output to stable
    error codes without exposing stack traces.
12. Return `status: success`, `sent: true`, recipient count, and attachment path
    only after successful subprocess completion.

## 5. Tests and validation

Before implementation, refresh the applicable official Antigravity
documentation, including projects, skills, rules, agent permissions, and the
changelog. If the repository-named URL reader remains unavailable, use direct
official-document reads and record that fallback.

Run:

1. `python3 .agents/scripts/check_libraries.py`
2. `python3 -m pytest .agents/workflows/ux-research/skills/send-email/tests -q`
3. `python3 -m pytest .agents/workflows/ux-research/tests/test_e2e_pipeline.py -q`
4. `python3 /Users/madebynham/.codex/skills/.system/skill-creator/scripts/quick_validate.py .agents/workflows/ux-research/skills/send-email`

Unit coverage will include:

- Valid, invalid, duplicate, empty, and header-injection addresses.
- BCC-only Apple Mail construction with empty To and CC.
- Relative, missing, unreadable, wrong-extension, out-of-report-directory, and
  handoff-mismatched attachments.
- Cancellation, missing approval, and an invalid approval token.
- Missing `osascript`, timeout, Apple Mail permission failure, and non-zero exit.
- Successful approved sending with subprocess mocked and argument boundaries
  asserted.
- Proof that no subprocess call occurs before approval.

The end-to-end test will generate the visualization, consume its returned
`output_file`, exercise the approval gate, and verify mocked successful sending
without launching Apple Mail.

## 6. Assumptions and explicit non-goals

- Apple Mail and `osascript` are runtime macOS facilities, not installable
  dependencies.
- Built-in AI performs draft suggestion only; deterministic Python performs
  validation and sending.
- The skill does not read `.env`, and `SKILL.md` contains no API Key section.
- HTML is attached as a file, not inserted as the email body.
- No To/CC fallback, SMTP support, external email provider, delivery tracking,
  scheduling, duplicate-send retries, or silent auto-send behavior will be
  added.
- After approval and implementation, all required checks will run before the
  repository-required commit and push.
