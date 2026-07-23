---
name: send-email
description: Prepares a BCC-only Apple Mail draft for the HTML report returned by visualize-insights, shows the complete draft for approval, and sends the report attachment only after the user provides the exact content-bound approval token. Use after visualize-insights in the ux-research workflow when users want to email a completed UX research report to specified recipients.
---

# Send Email

## Description

Prepare and send the final UX research HTML report through Apple Mail. Use
built-in AI only to suggest the subject and plain-text body; use the deterministic
`scripts/send_email.py` helper for validation, approval enforcement, and sending.
Always keep To and CC empty, place every recipient in BCC, and never send before
the user reviews the complete draft and repeats its exact approval token.

## Input

- **Type**: `dict`
- **Location**: `request_body`
- **Format**:
  - `visualization_result` (dict, required) — Successful or manifest-validated
    skipped result returned by `visualize-insights`. Its absolute `output_file`
    must be passed unchanged.
  - `folder_path` (string, required) — Absolute research project folder whose
    report directory is `<folder_path>/Interview/Research Report`.
  - `bcc_recipients` (array of strings, required) — Runtime recipients supplied
    by the user. At least one valid address is required.
  - `subject` (string, required) — User-reviewed subject suggested by built-in AI
    or edited by the user.
  - `body` (string, required) — User-reviewed plain-text message suggested by
    built-in AI or edited by the user.
  - `approval_token` (string, required only for sending) — Exact token returned
    for the unchanged draft and repeated by the user.
- **Input File(s)**:
  - `<project_name>.html` — Exact absolute `output_file` returned by
    `visualize-insights`, normally under `Interview/Research Report`.
- **Example**:

  ```json
  {
    "visualization_result": {
      "status": "success",
      "output_file": "/project/Interview/Research Report/Example.html"
    },
    "folder_path": "/project",
    "bcc_recipients": ["research@example.com"],
    "subject": "Example UX research report",
    "body": "Please find the completed UX research report attached."
  }
  ```

## Output

- **Type**: `dict`
- **Location**: `response_body`
- **Format**:
  - Draft phase:
    - `status`: `awaiting_approval`
    - `sent`: `false`
    - `draft`: Complete immutable draft with `draft_id`, empty `to` and `cc`,
      BCC recipients, subject, body, and attachment path.
    - `approval_token`: Content-bound token that must be repeated exactly.
  - Send phase:
    - `status`: `success`, `cancelled`, or `error`
    - `sent`: Boolean send confirmation.
    - `recipient_count`: Number of BCC recipients on success.
    - `attachment_path`: Exact report path on success.
    - `error`: Stable `code` and safe `message` for cancelled or failed sends.
- **Example awaiting approval**:

  ```json
  {
    "status": "awaiting_approval",
    "sent": false,
    "draft": {
      "draft_id": "<sha256>",
      "to": [],
      "cc": [],
      "bcc": ["research@example.com"],
      "subject": "Example UX research report",
      "body": "Please find the completed UX research report attached.",
      "attachment_path": "/project/Interview/Research Report/Example.html"
    },
    "approval_token": "APPROVE-SEND-EMAIL:<sha256>"
  }
  ```

## Custom Instructions

- Ask who should receive the report every time this skill runs. Never reuse or
  infer recipients from a prior run.
- Use built-in AI to suggest a concise subject and plain-text body based on the
  project name and completed report. Do not use an API key or external LLM.
- Call `prepare_email_draft()` with the exact visualization result, absolute
  project folder, recipients, subject, and body.
- Show the user the entire returned draft: empty To and CC, all BCC recipients,
  subject, body, exact attachment, and approval token.
- Pause with `awaiting_approval`. Treat `yes`, `approved`, ambiguous responses,
  edits, or a non-matching token as not approved.
- If the user changes any recipient, subject, body, or attachment, prepare and
  show a new draft with a new token.
- Call `send_approved_email()` only after the user repeats the exact current
  token. Never call the sender speculatively.
- Never retry a timeout or uncertain Apple Mail result because the first send
  may already have been accepted.
- Preserve the generated report if drafting is cancelled or sending fails.
- Clean up temporary files immediately after completion. This skill creates no
  temporary email or report copies.

## Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Orchestrator as UX Research
    participant AI as Built-in AI
    participant Skill as send-email
    participant Mail as Apple Mail

    Orchestrator->>User: Ask for BCC recipients
    User-->>Orchestrator: Recipient addresses
    Orchestrator->>AI: Suggest subject and plain-text body
    AI-->>Orchestrator: Draft content
    Orchestrator->>Skill: prepare_email_draft(...)
    Skill-->>Orchestrator: awaiting_approval, complete draft, token
    Orchestrator->>User: Show full draft and exact token
    alt Exact current token supplied
        User-->>Orchestrator: APPROVE-SEND-EMAIL:<sha256>
        Orchestrator->>Skill: send_approved_email(...)
        Skill->>Mail: BCC-only message with HTML attachment
        Mail-->>Skill: SENT
        Skill-->>Orchestrator: success
    else Cancelled, edited, or ambiguous response
        User-->>Orchestrator: No exact token
        Orchestrator-->>User: cancelled; report preserved
    end
```

## Error Handling & Fallbacks

| Error Code | Message | Fallback Behavior |
| --- | --- | --- |
| `INVALID_INPUT` | Draft, folder, or timeout input is invalid. | Do not send; correct the input and prepare a new draft. |
| `INVALID_VISUALIZATION_HANDOFF` | Visualization did not return a usable report. | Halt email drafting and preserve the report workflow result. |
| `INVALID_ATTACHMENT` | HTML report is missing, unreadable, or not a regular absolute `.html` file. | Do not send; regenerate or restore the report. |
| `ATTACHMENT_OUTSIDE_REPORT_DIR` | Attachment resolves outside `Interview/Research Report`. | Do not send; use the exact visualization handoff. |
| `INVALID_RECIPIENTS` | BCC list is empty or contains an invalid address. | Ask the user for corrected recipients and prepare a new draft. |
| `INVALID_SUBJECT`, `INVALID_BODY` | Draft content is empty or unsafe. | Suggest corrected content and prepare a new draft. |
| `NOT_APPROVED` | Exact current approval token was not supplied. | Return `cancelled`; never invoke Apple Mail. |
| `OSASCRIPT_NOT_FOUND` | AppleScript is unavailable. | Preserve the report and explain that Apple Mail sending requires macOS. |
| `SEND_TIMEOUT` | Mail did not confirm before the timeout. | Do not retry; ask the user to check Sent and Drafts. |
| `MAIL_AUTOMATION_DENIED` | macOS denied Apple Mail automation. | Ask the user to allow automation access; prepare a fresh approval before retrying. |
| `MAIL_SEND_FAILED` | Apple Mail returned a definite failure. | Preserve the report and surface the safe error. |
| `UNEXPECTED_OSASCRIPT_OUTPUT` | Mail returned no unambiguous confirmation. | Do not retry; ask the user to check Sent and Drafts. |
| `INTERNAL_ERROR` | An unexpected safe failure occurred. | Preserve the report and return the stable code without a stack trace. |

## Known Bugs & Resolutions

> **Agent Rule (Error Handling & Bug Documentation):** When this skill encounters
> an error during input validation, approval, or Apple Mail execution, first
> propose a solution to the user. If the user approves and the fix succeeds,
> document the bug, cause, resolution, and regression protection here.

| Bug / Error | Cause | Resolution |
| --- | --- | --- |
| Valid drafts returned `INTERNAL_ERROR` during recipient parsing | The implementation used the Python 3.13-only `parseaddr(..., strict=True)` parameter, but this workflow runs on Python 3.12. | Removed the unsupported parameter, retained explicit control-character, whitespace, parse-equality, `@`, local-part, and domain validation, and added regression coverage through all valid and invalid recipient tests. |

## Performance Improvement Solutions

- [x] Use deterministic local validation and one AppleScript invocation only
  after approval.
- [x] Avoid external APIs, dependencies, retries, and temporary report copies.
- [x] Cover approval, validation, Apple Mail failures, and the parent workflow
  handoff with mocked tests.
