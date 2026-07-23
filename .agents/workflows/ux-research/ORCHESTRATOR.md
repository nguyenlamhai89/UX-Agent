---
name: UX Research Report
description: Coordinates the complete UX research pipeline from transcription through customer journey mapping and visualization, then prepares and sends the approved HTML report via Gmail SMTP.
---

# UX Research Report

## Description

This parent workflow coordinates the complete research sequence:
`ux-interview` → `ux-map-journey` → `visualize-insights` → `send-email`. It
preserves each child workflow's approval gates, passes only canonical successful
outputs to the next stage, produces an atomic freshness-aware HTML report, and
offers CC Gmail SMTP delivery after a separate final-draft approval.

The parent orchestrator owns coordination, environment access, and its final
delivery stages. It reads the workspace-root `.env` once, passes only the API
keys and credentials required by each child orchestrator or skill, invokes its
workflow-owned `visualize-insights` skill, and finishes with its workflow-owned
`send-email` skill. Child orchestrators and skills never read `.env` directly.

## Routing Logic & Execution Flow

Route complete UX research requests here when the user wants transcription,
mapping, insight saturation, a journey map, and the final visualization in one
pipeline. Isolated requests remain routed to the relevant child workflow or
workflow-owned skill.

0. **Dependency verification and environment loading** — Run
   `python3 .agents/scripts/check_libraries.py`. Warn about missing or outdated
   packages, but halt only when the dependency required by the next step is
   unavailable. Read the workspace-root `.env` once and resolve the API keys and
   credentials (`ELEVENLABS_API_KEY`, `GMAIL_APP_USERNAME`, `GMAIL_APP_PASSWORD`)
   required by this run. Never log, persist in artifacts, or expose key values.
1. **Run `ux-interview`** — Pass the absolute `folder_path`, required keyterms,
   and only the `ELEVENLABS_API_KEY` loaded by the parent. The child orchestrator
   must not read `.env`; it injects the received key only into the
   `transcribe-audios` process. Preserve all approval gates and continue only
   after the child reports a complete current canonical mapping and successful
   insight publication.
2. **Validate the transcription handoff** — Require these absolute files:
   - `<folder_path>/Interview/mapped-transcript.md`
   - `<folder_path>/Interview/insights.md`
   - exactly one matching `<folder_path>/Interview/transcript-*.md` or legacy
     `transcript_*.md` file for each mapped interviewee.
3. **Ask for approval** — Present the canonical mapped transcript and insight
   paths. Stop until the user approves the `ux-map-journey` stage.
4. **Run `ux-map-journey`** — Pass `<folder_path>/Interview` as its `folder_path` so it
   consumes the canonical mapped transcript and writes
   `<folder_path>/Interview/Journey Map/journey-map.md`. Preserve all child
   approval gates.
5. **Validate and approve the journey handoff** — Require a successful journey
   map, present its absolute path, and stop until the user approves final report
   generation.
6. **Run `visualize-insights`** — Pass the canonical paths explicitly:
   ```json
   {
     "insights_path": "<folder_path>/Interview/insights.md",
     "transcript_path": "<folder_path>/Interview/mapped-transcript.md",
     "full_transcript_paths": ["<absolute matching transcript paths>"],
     "journey_path": "<folder_path>/Interview/Journey Map/journey-map.md",
     "media_paths": ["<absolute media paths declared or resolved by the parent>"],
     "output_dir": "<folder_path>/Interview/Research Report",
     "project_name": "<project_name>",
     "open_browser": false
   }
   ```
7. **Freshness and skip rule** — Accept `status: skipped` only when the
   visualization manifest reports `status: success`, its input signature covers
   the canonical insights, mapped transcript, full transcripts, journey map,
   media metadata, and all HTML templates, and the recorded output hash matches
   the current HTML file. File existence alone is never a valid skip signal.
8. **Ask for recipients and draft the email** — Always ask who should receive
   the report. Place every recipient in CC and keep To and BCC empty. Pass the
   exact visualization `output_file` unchanged and `sender_email` (`GMAIL_APP_USERNAME`)
   to `send-email`. The skill deterministically generates a formal Vietnamese email
   with instructions for opening the attached HTML report.
9. **Show the final draft and pause** — Call `prepare_email_draft()`, then show
   the complete draft: configured From address, empty To and BCC, all CC recipients,
   subject, body, attachment path, and content-bound approval token. Stop with
   `awaiting_approval` until the user repeats that exact token. Any edit requires
   a newly prepared draft and token; `yes` or `approved` alone is insufficient.
10. **Send once through Gmail SMTP** — Call `send_approved_email()` with `gmail_app_username`
    and `gmail_app_password` read by parent only after the exact current token is supplied.
    Never retry a timeout or uncertain result because Gmail SMTP may already have accepted the message.
11. **Return the final result** — Return the absolute HTML and manifest paths,
    child workflow artifacts, input signature, structured warnings, and nested
    `email` result. Email cancellation or failure does not invalidate the
    successfully generated HTML report.

**Execution Rule:** When a child workflow completes and generates an output,
the orchestrator MUST pause and ask the user for approval before entering the
next stage. A partial or stale child result halts the pipeline.

## Available Workflows and Skills

- **[UX Interview](../ux-interview/ORCHESTRATOR.md)** — Produces canonical
  full transcripts, `mapped-transcript.md`, and `insights.md`.
- **[UX Map Journey](../ux-map-journey/ORCHESTRATOR.md)** — Produces the canonical
  `Journey Map/journey-map.md` from the mapped transcript.
- **[visualize-insights](./skills/visualize-insights/SKILL.md)** — Produces
  the final interactive HTML report and freshness manifest.
- **[send-email](./skills/send-email/SKILL.md)** — Prepares a formal CC
  draft from the configured Gmail sender and sends the exact HTML report through
  Gmail SMTP after exact-token approval.

The local `skills/` directory contains skills owned directly by this parent
workflow. Shared cross-workflow skills remain under `.agents/skills/`.

## Input

- **Type**: `dict`
- **Location**: `request_body`
- **Format**:
  - `folder_path` (string, required) — Absolute research project folder.
  - `project_name` (string, required) — Safe 1-120 character output name.
  - `media_paths` (array of strings, optional) — Explicit absolute interview
    media paths used for duration statistics.
  - `open_browser` (boolean, optional, default `false`) — Open the final report.
  - `max_input_bytes` (integer, optional, default `52428800`) — Maximum total
    size of text inputs passed to visualization.
  - `force_visualization` (boolean, optional, default `false`) — Ignore a
    current visualization manifest and rebuild.

## Output

- **Type**: `dict`
- **Location**: `response_body`
- **Format**:
  - `status`: `success`, `skipped`, or `error`.
  - `output_file`: Absolute final HTML path.
  - `manifest_file`: Absolute visualization manifest path.
  - `input_signature`: Final visualization signature.
  - `artifacts`: Canonical mapped transcript, insights, full transcripts, and
    journey map paths.
  - `warnings`: Structured non-fatal warning objects.
  - `email`: Nested `awaiting_approval`, `success`, `cancelled`, or `error`
    result from `send-email`, including the complete draft during approval or
    the send outcome afterward.

## Environment Access (.env)

- **Allowed to access the workspace-root `.env`**: `true`
- **Environment owner**: `ux-research` is the only workflow in the complete
  pipeline allowed to read `.env`.
- **Delegation rule**: Pass only the specific keys required by a child
  orchestrator or skill. Neither child orchestrators nor skills may read `.env` directly.

| Key Name | Purpose | Delegation path |
| --- | --- | --- |
| `ELEVENLABS_API_KEY` | Interview audio transcription | `.env` → `ux-research` → `ux-interview` → `transcribe-audios` process environment |
| `GMAIL_APP_USERNAME` | Gmail sender address / account username | `.env` → `ux-research` → `send-email` parameter |
| `GMAIL_APP_PASSWORD` | Gmail App Password for SMTP authentication | `.env` → `ux-research` → `send-email` parameter |

## Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Env as workspace .env
    participant Parent as UX Research Report
    participant UXI as UX Interview
    participant UXM as UX Map Journey
    participant VIS as visualize-insights
    participant EMAIL as send-email
    participant SMTP as Gmail SMTP Server

    User->>Parent: folder_path and project_name
    Parent->>Env: Read required API keys & credentials once
    Env-->>Parent: ELEVENLABS_API_KEY, GMAIL_APP_USERNAME, GMAIL_APP_PASSWORD
    Parent->>UXI: Run with folder_path and required API key
    UXI-->>Parent: Canonical transcripts, mapping, and insights
    Parent-->>User: Approve journey mapping
    User->>Parent: Approved
    Parent->>UXM: Run with Interview folder
    UXM-->>Parent: Canonical journey-map.md
    Parent-->>User: Approve final visualization
    User->>Parent: Approved
    Parent->>VIS: Pass all canonical absolute paths
    alt Current manifest and output hash match
        VIS-->>Parent: skipped and current report
    else Generation required
        VIS-->>Parent: success, HTML, and manifest
    end
    Parent->>User: Ask for CC recipients
    User-->>Parent: Recipient addresses
    Parent->>EMAIL: Prepare exact report draft with GMAIL_APP_USERNAME
    EMAIL-->>Parent: Complete draft and approval token
    Parent-->>User: Review full draft and exact token
    alt Exact current token supplied
        User-->>Parent: APPROVE-SEND-EMAIL:<sha256>
        Parent->>EMAIL: Send approved draft with GMAIL_APP_USERNAME & GMAIL_APP_PASSWORD
        EMAIL->>SMTP: Connect TLS smtp.gmail.com:587, auth, sendmail
        SMTP-->>EMAIL: OK
        EMAIL-->>Parent: success
    else Cancelled, edited, or ambiguous
        User-->>Parent: No exact token
        Parent-->>User: Email cancelled; report preserved
    end
    Parent-->>User: Report artifacts and nested email result
```

## Error Handling & Fallbacks

| Error Code | Fallback Behavior |
| --- | --- |
| `MISSING_API_KEY` | Ask the user for the ElevenLabs key and store it only through the authorized parent environment flow. |
| `PARTIAL_MAPPING`, `UPSTREAM_MAPPING_NOT_SUCCESS`, `UPSTREAM_SIGNATURE_MISMATCH` | Halt before insights and preserve the last-known-good canonical mapping. |
| `PARTIAL_EXTRACTION`, `PARTIAL_CONSOLIDATION`, `EXTRACTION_VALIDATION_FAILED`, `CONSOLIDATION_VALIDATION_FAILED` | Halt before journey mapping and preserve prior insight outputs. |
| `SKILL_FAILURE`, `INVALID_INPUT` from `ux-map-journey` | Halt before visualization and present the failing journey stage. |
| `INPUT_READ_ERROR`, `FULL_TRANSCRIPT_INVALID`, `PARSING_ERROR`, `JOURNEY_ERROR` | Halt visualization and identify the exact handoff artifact to repair. |
| `INPUT_TOO_LARGE` | Ask the user to reduce inputs or intentionally raise `max_input_bytes`. |
| `TEMPLATE_ERROR`, `OUTPUT_PATH_INVALID`, `OUTPUT_WRITE_ERROR` | Preserve the last-known-good report and manifest; do not treat file existence as success. |
| `BROWSER_OPEN_ERROR` | Return success with a structured warning because the report itself remains valid. |
| `INVALID_VISUALIZATION_HANDOFF`, `INVALID_ATTACHMENT`, `ATTACHMENT_OUTSIDE_REPORT_DIR` from `send-email` | Halt email drafting, preserve the successful report, and identify the handoff to repair. |
| `INVALID_RECIPIENTS` | Ask for corrected CC recipients and prepare a new content-bound token. |
| `GMAIL_CONFIG_MISSING` | Prompt user to provide `GMAIL_APP_USERNAME` and `GMAIL_APP_PASSWORD` in root `.env`. |
| `NOT_APPROVED` | Return email status `cancelled`; never invoke Gmail SMTP and preserve the report. |
| `SMTP_AUTH_FAILED` | Ask user to verify `GMAIL_APP_USERNAME` and `GMAIL_APP_PASSWORD` in `.env`. |
| `SEND_TIMEOUT` | Do not retry; preserve the report and ask the user to check Sent folder. |
| `SMTP_SEND_FAILED` | Preserve the report and return the safe nested email error. |
| `INTERNAL_ERROR` | Halt and return the stable code without exposing a stack trace. |

## Known Bugs & Resolutions

| Bug / Error | Cause | Resolution |
| --- | --- | --- |
