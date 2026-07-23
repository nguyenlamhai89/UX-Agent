---
name: send-email
description: Prepares a formal Vietnamese BCC-only Apple Mail draft from nguyenlamhai89@gmail.com for the HTML report returned by visualize-insights, shows the complete draft for approval, and sends the exact report attachment only after the user provides the content-bound approval token. Use after visualize-insights in the ux-research workflow when users want to email a completed UX research report to specified recipients.
---

# Send Email

## Description

Prepare and send the final UX research HTML report through Apple Mail from
`nguyenlamhai89@gmail.com`. Use the deterministic `scripts/send_email.py` helper
to generate a formal Vietnamese subject and body, validate the visualization
handoff, enforce approval, and send the message. Always keep To and CC empty,
place every recipient in BCC, attach the exact `output_file` returned by
`visualize-insights`, and never send before the user reviews the complete draft
and repeats its exact approval token.

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
    "bcc_recipients": ["research@example.com"]
  }
  ```

## Output

- **Type**: `dict`
- **Location**: `response_body`
- **Format**:
  - Draft phase:
    - `status`: `awaiting_approval`
    - `sent`: `false`
    - `draft`: Complete immutable draft with `draft_id`, fixed `from` address,
      empty `to` and `cc`, BCC recipients, formal subject and body, and attachment path.
    - `approval_token`: Content-bound token that must be repeated exactly.
  - Send phase:
    - `status`: `success`, `cancelled`, or `error`
    - `sent`: Boolean send confirmation.
    - `sender`: Fixed From address on success: `nguyenlamhai89@gmail.com`.
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
      "from": "nguyenlamhai89@gmail.com",
      "to": [],
      "cc": [],
      "bcc": ["research@example.com"],
      "subject": "[Báo cáo UX Research] Example",
      "body": "Kính gửi Quý Anh/Chị, ... Hướng dẫn mở báo cáo: tải file HTML đính kèm và mở bằng Chrome, Edge, hoặc Safari.",
      "attachment_path": "/project/Interview/Research Report/Example.html"
    },
    "approval_token": "APPROVE-SEND-EMAIL:<sha256>"
  }
  ```

## Custom Instructions

- Ask who should receive the report every time this skill runs. Never reuse or
  infer recipients from a prior run.
- Use `nguyenlamhai89@gmail.com` as the fixed sender. Do not accept a sender
  address from the user or switch to a different Apple Mail account.
- Generate a formal Vietnamese subject and plain-text body from the exact HTML
  filename returned by `visualize-insights`. Include instructions to download
  the attachment and open it in Chrome, Edge, or Safari.
- Call `prepare_email_draft()` with the exact visualization result, absolute
  project folder, and BCC recipients.
- Show the user the entire returned draft: fixed From address, empty To and CC,
  all BCC recipients, subject, body, exact attachment, and approval token.
- Pause with `awaiting_approval`. Treat `yes`, `approved`, ambiguous responses,
  edits, or a non-matching token as not approved.
- If the user changes any recipient or attachment, prepare and show a new draft
  with a new token. The sender, formal subject, and formal body remain fixed.
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
    Orchestrator->>Skill: prepare_email_draft(...)
    Skill-->>Orchestrator: awaiting_approval, complete draft, token
    Orchestrator->>User: Show full draft and exact token
    alt Exact current token supplied
        User-->>Orchestrator: APPROVE-SEND-EMAIL:<sha256>
        Orchestrator->>Skill: send_approved_email(...)
        Skill->>Mail: Send from fixed account, BCC-only HTML attachment
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
| `SENDER_ACCOUNT_NOT_CONFIGURED` | Apple Mail cannot use `nguyenlamhai89@gmail.com` as the sender. | Add or enable that account in Apple Mail, then prepare a new draft. |
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
