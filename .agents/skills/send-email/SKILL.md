---
name: send-email
description: Prepares a formal Vietnamese CC draft from a configured Gmail sender for the HTML report returned by visualize-insights, shows the complete draft for approval, and sends the exact report attachment via Gmail SMTP (smtplib) only after the user provides the content-bound approval token. Use after visualize-insights when users want to email a completed UX research report to specified recipients.
---

# Send Email

## Description

Prepare and send the final UX research HTML report through Gmail SMTP (`smtp.gmail.com:587`) using the Gmail account supplied by the caller from `.env` (`GMAIL_APP_USERNAME` and `GMAIL_APP_PASSWORD`). The skill itself never reads `.env`. Use the deterministic `scripts/send_email.py` helper to generate a formal Vietnamese subject and body, validate the visualization handoff, enforce approval, and send the message. Always ask the user who should receive the report, keep To and BCC empty, place every recipient in CC, attach the exact `output_file` returned by `visualize-insights`, and never send before the user reviews the complete draft and repeats its exact approval token.

## Input

- **Type**: `dict`
- **Location**: `request_body`
- **Format**:
  - `visualization_result` (dict, required) — Successful or manifest-validated
    skipped result returned by `visualize-insights`. Its absolute `output_file`
    must be passed unchanged.
  - `folder_path` (string, required) — Absolute research project folder whose
    report directory is `<folder_path>/Interview/Research Report`.
  - `cc_recipients` (array of strings, required) — Recipient addresses collected
    from the user at runtime. At least one valid address is required. All
    recipients are always sent through CC.
  - `gmail_app_username` (string, required) — Gmail account username loaded
    from `.env` by the calling orchestrator and used as the draft's From address.
  - `gmail_app_password` (string, required for sending) — Gmail App Password
    loaded from `.env` by the calling orchestrator.
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
    "cc_recipients": ["research@example.com"],
    "gmail_app_username": "researcher@example.com"
  }
  ```

## Output

- **Type**: `dict`
- **Location**: `response_body`
- **Format**:
  - Draft phase:
    - `status`: `awaiting_approval`
    - `sent`: `false`
    - `draft`: Complete immutable draft with `draft_id`, configured `from` address,
      empty `to` and `bcc`, CC recipients, formal subject and body, and attachment path.
    - `approval_token`: Content-bound token that must be repeated exactly.
  - Send phase:
    - `status`: `success`, `cancelled`, or `error`
    - `sent`: Boolean send confirmation.
    - `sender`: The `gmail_app_username` supplied by the caller and shown in the approved draft.
    - `recipient_count`: Number of CC recipients on success.
    - `attachment_path`: Exact report path on success.
    - `error`: Stable `code` and safe `message` for cancelled or failed sends.
- **Example awaiting approval**:

  ```json
  {
    "status": "awaiting_approval",
    "sent": false,
    "draft": {
      "draft_id": "<sha256>",
      "from": "researcher@example.com",
      "to": [],
      "cc": ["research@example.com"],
      "bcc": [],
      "subject": "[Báo cáo UX Research] Example",
      "body": "Kính gửi Anh/Chị, ... Hướng dẫn mở báo cáo: tải file HTML đính kèm và mở bằng Chrome, Edge, hoặc Safari.",
      "attachment_path": "/project/Interview/Research Report/Example.html"
    },
    "approval_token": "APPROVE-SEND-EMAIL:<sha256>"
  }
  ```

## Custom Instructions

- Ask who should receive the report every time this skill runs. Prompt the user
  for all recipients to CC. Never reuse, infer, or hard-code recipients from a
  prior run.
- Use `GMAIL_APP_USERNAME` supplied by the calling orchestrator from `.env` as
  the sender. The skill must not read `.env`, use a hard-coded sender, or accept
  a separate user-provided sender address.
- Pass every collected recipient only through `cc_recipients`; reject
  `bcc_recipients` and keep both To and BCC empty.
- Generate a formal Vietnamese subject and plain-text body from the exact HTML
  filename returned by `visualize-insights`. Include instructions to download
  the attachment and open it in Chrome, Edge, or Safari.
- Call `prepare_email_draft()` with the exact visualization result, absolute
  project folder, runtime CC recipients, and the caller-supplied
  `gmail_app_username`.
- Show the user the entire returned draft: configured From address, empty To and BCC,
  all CC recipients, subject, body, exact attachment, and approval token.
- Pause with `awaiting_approval`. Allow the user to approve either by typing simplified affirmative keywords (`ok`, `yes`, `approved`, `y`, `gửi`, `gui`, `approve`, `confirm`) or by repeating the exact approval token.
- If the user changes any recipient or attachment, prepare and show a new draft
  with a new token. The sender, formal subject, and formal body remain fixed.
- Call `send_approved_email()` with the same `gmail_app_username` and the
  caller-supplied `gmail_app_password` only after the user confirms with an
  affirmative token or repeats the exact current token. The skill rejects a
  username that does not match the approved draft sender. Never call the SMTP
  server speculatively.
- Never retry a timeout or uncertain SMTP response because the first send
  may already have been accepted by the remote mail server.
- Preserve the generated report if drafting is cancelled or sending fails.
- Clean up temporary files immediately after completion. This skill creates no
  temporary email or report copies.

## Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Orchestrator as Calling Orchestrator
    participant AI as Built-in AI
    participant Skill as send-email
    participant SMTP as Gmail SMTP Server

    Orchestrator->>User: Ask for CC recipients
    User-->>Orchestrator: Recipient addresses
    Orchestrator->>Skill: prepare_email_draft(...)
    Skill-->>Orchestrator: awaiting_approval, complete draft, token
    Orchestrator->>User: Show full draft and approval instructions
    alt Affirmative response (ok, yes, gửi) or exact token supplied
        User-->>Orchestrator: "ok" / "gửi" / APPROVE-SEND-EMAIL:<sha256>
        Orchestrator->>Skill: send_approved_email(app_username, app_password)
        Skill->>SMTP: TLS Connect (smtp.gmail.com:587) & Auth
        Skill->>SMTP: CC envelope send (MIME + HTML attachment)
        SMTP-->>Skill: OK
        Skill-->>Orchestrator: success
    else Cancelled, edited, or non-affirmative response
        User-->>Orchestrator: Cancel / invalid input
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
| `INVALID_RECIPIENTS` | CC list is empty or contains an invalid address. | Ask the user for corrected recipients and prepare a new draft. |
| `GMAIL_CONFIG_MISSING` | Gmail credentials are missing from the caller payload. | Ask the calling orchestrator to load `GMAIL_APP_USERNAME` and `GMAIL_APP_PASSWORD` from `.env` and pass them to the skill. |
| `GMAIL_SENDER_MISMATCH` | The Gmail username used for SMTP does not match the approved From address. | Prepare a new draft using the same `GMAIL_APP_USERNAME` that will be used for SMTP. |
| `NOT_APPROVED` | Neither approval token nor affirmative keyword (`ok`, `yes`, `gửi`) was provided. | Return `cancelled`; never invoke Gmail SMTP. |
| `SMTP_AUTH_FAILED` | Gmail authentication failed. | Check `GMAIL_APP_USERNAME` and `GMAIL_APP_PASSWORD` in `.env`. |
| `SEND_TIMEOUT` | Gmail SMTP server did not respond before timeout. | Do not retry; ask the user to check Sent folder. |
| `SMTP_SEND_FAILED` | Gmail SMTP connection or dispatch failed. | Preserve the report and surface safe error. |
| `INTERNAL_ERROR` | An unexpected safe failure occurred. | Preserve the report and return the stable code without a stack trace. |

## Known Bugs & Resolutions

> **Agent Rule (Error Handling & Bug Documentation):** When this skill encounters
> an error during input validation, approval, or Gmail SMTP execution, first
> propose a solution to the user. If the user approves and the fix succeeds,
> document the bug, cause, resolution, and regression protection here.

| Bug / Error | Cause | Resolution |
| --- | --- | --- |
| Valid drafts returned `INTERNAL_ERROR` during recipient parsing | The implementation used the Python 3.13-only `parseaddr(..., strict=True)` parameter, but this workflow runs on Python 3.12. | Removed the unsupported parameter, retained explicit control-character, whitespace, parse-equality, `@`, local-part, and domain validation, and added regression coverage through all valid and invalid recipient tests. |
| Report attachment directly in `Interview/` raised `ATTACHMENT_OUTSIDE_REPORT_DIR` | `_validate_attachment` enforced `Interview/Research Report` strictly, missing reports generated directly inside `Interview/`. | Updated `_validate_attachment` and `prepare_email_draft` to accept files under `Interview/` and `Interview/Research Report/`, and added unit test coverage. |
| macOS Apple Mail app dependency failed on non-macOS or non-AppleMail setups | Skill relied on macOS AppleScript `osascript`. | Converted skill exclusively to pure-Python `smtplib` using `smtp.gmail.com:587` with TLS, dynamic `GMAIL_APP_USERNAME` and `GMAIL_APP_PASSWORD` credentials passed via the calling orchestrator. |
| HTML report attachment opened in TextEdit instead of browser in macOS | Attachment MIME type was set to generic `application/octet-stream`, causing OS mail clients (e.g. Apple Mail) to route `.html` files to TextEdit. | Changed attachment MIME type to `text/html` with `charset="utf-8"` (`MIMEBase("text", "html", charset="utf-8")`) so email clients and macOS recognize it as a web document and open it in the default browser. |
| Non-ASCII token comparison (e.g., `gửi`) raised `TypeError` in `hmac.compare_digest` | `hmac.compare_digest` in Python raises `TypeError` when comparing strings containing non-ASCII characters. | Encoded both strings to UTF-8 bytes (`approval_token.encode("utf-8")`, `expected_token.encode("utf-8")`) before calling `hmac.compare_digest`, added `unicodedata.normalize("NFC", ...)` for Unicode-insensitive keyword matching, and expanded unit tests. |
| Sender and recipient routing could be hard-coded or fall back to BCC | The draft used a fixed sender default and accepted `bcc_recipients` as an alternate input. | Require the caller-supplied `GMAIL_APP_USERNAME`, require runtime `cc_recipients`, reject BCC input, enforce sender/SMTP username matching, and add regression tests. |
| SMTP failure tests were blocked before reaching the mocked SMTP server | Regression fixtures passed a username different from the approved draft sender after sender binding became mandatory. | Updated SMTP failure fixtures to reuse the draft's Gmail username and preserved explicit sender-mismatch coverage. |

## Performance Improvement Solutions

- [x] Use deterministic local validation and one Python smtplib connection only after approval.
- [x] Avoid external OS dependencies (osascript), retries, and temporary report copies.
- [x] Cover approval, validation, Gmail SMTP failures, and the caller handoff with mocked tests.
