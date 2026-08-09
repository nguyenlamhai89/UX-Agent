---
name: UX Interview
description: Orchestrates UX research workflows by routing requests to transcribe interview audio, extract questionnaire tables from images, and map transcript responses to questionnaire structures.
---

# UX Interview

## Description
The UX Interview orchestrates UX research tasks, delegating user requests to the appropriate skills. Its core capabilities include:
1. **Questionnaire Table Extraction**: Reading a question table from a Google Sheet link, Excel file (.xlsx/.xls tab "2. Questionnaire"), or image to produce a structured `full-questionnaire.md`.
2. **Audio Transcription**: Converting interview audio into Markdown transcripts using ElevenLabs Speech to Text.
3. **Transcript Mapping**: Mapping interviewee responses from transcripts to the questionnaire structure.
4. **Insights Saturation**: Synthesizing responses into a structured `insights.md` and saturation matrix.

Routes requests here when the user mentions UX research, transcription, questionnaire tables, transcript mapping, or insights synthesis.

## Routing Logic & Execution Flow
The orchestrator follows a sequential flow. **Incremental Execution**: Before most steps, validate existing outputs before skipping. For `map-transcript`, file existence is never a valid skip signal: always run `mapping_pipeline.py prepare <folder_path>` first and skip only when it returns `canonical_current: true` for the complete transcript source set.
The orchestrator creates an `Interview` folder inside the provided `folder_path`
and instructs all skills to place their outputs inside this `Interview` folder.
It receives required API keys from the parent `ux-research` orchestrator and
never reads `.env` directly.

**Sequential Pipeline**:
0. **Dependency Verification**: Run the package validation script `.agents/scripts/check_libraries.py` to ensure all external dependencies (`elevenlabs`, `matplotlib`, `pytest`) are installed and up to date. Show warning/suggestions if needed.
1. **Folder Creation & Data Preparation**: Create a folder named `Interview` inside the provided `folder_path`. Move all input files (e.g., images and audio files) from `folder_path` into this `Interview` folder. All subsequent skills MUST read their inputs from and place their outputs inside this `Interview` folder.
2. **Questionnaire Extraction** (`create-questionnaire-table`): Extracts table from Google Sheet link, Excel file (tab `"2. Questionnaire"`), or image to `full-questionnaire.md`. If no Excel questionnaire file (`.xlsx`), Google Sheet URL, or question table image is found, halt and prompt the user to upload an Excel questionnaire file (`.xlsx`) downloaded from the template into the project folder, or provide a public Google Sheet URL.
3. **Approval**: **[CRITICAL] STOP** and wait for user approval. Do NOT proceed until the user replies.
4. **Audio Transcription** (`transcribe-audios`): First run
   `python3 .agents/workflows/ux-interview/skills/transcribe-audios/scripts/check_elevenlabs_docs.py --strict`
   to fetch and verify the current official ElevenLabs Speech to Text overview,
   tutorial/quickstart, batch how-to guides, realtime event reference, and API
   reference. If the live contract has changed or the docs are unavailable,
   stop before making an ElevenLabs request and review the docs. Then require
   `ELEVENLABS_API_KEY` supplied by `ux-research`, inject it into the skill
   process environment, and transcribe with `language_code=vi` and the
   documented batch options. Never read `.env` or expose keys in
   logs or output artifacts. **Halts workflow and returns detailed per-file
   error codes on failure.**
5. **Approval**: **[CRITICAL] STOP** and wait for user approval. Do NOT proceed until the user replies.
6. **Transcript Mapping** (`map-transcript`): Run the controller preflight, process controller-issued tasks in batches of at most 4 Antigravity subagents, validate and atomically promote each candidate, then finalize. Every mapped quote MUST be a complete verbatim turn from that interviewee's source transcript, with the exact timestamp, wording, spelling, and punctuation; never truncate, paraphrase, translate, or correct it. The controller enforces this source equality before promotion. A `partial` result MUST halt the workflow before insights; `mapped-transcript.md` is current only after a `success` finalization. The controller also generates review tables in groups of 5 interviewees and `mapping-review-manifest.md` for larger studies such as 20 participants.
7. **Approval**: **[CRITICAL] STOP** and wait for user approval. Do NOT proceed until the user replies.
8. **Insights Saturation** (`saturate-insights`): Run only after `map-transcript` finalization returns `status: success`; the adjacent mapping manifest must also record `canonical_current: true`. Pass exactly `{"mapped_transcript_file": "<folder_path>/Interview/mapped-transcript.md"}`; do not pass the folder, per-interviewee mappings, partial/review files, or `temp_insights.json`. The skill verifies the adjacent mapping manifest, extracts participants in controller-bounded batches of at most 4, grounds every quote against the canonical combined table, consolidates evidence in bounded batches, and atomically publishes auditable insight outputs.
9. **Approval**: **[CRITICAL] STOP** and wait for user approval. Workflow complete.


**Isolated Requests (Keyword-based)**:
| Intent | Keywords | Routed to Skill |
| --- | --- | --- |
| Audio Transcription | "transcribe", "audio", "interview transcript" | `transcribe-audios` |
| Questionnaire Extraction | "questionnaire", "google sheet", "excel questionnaire", "extract table" | `create-questionnaire-table` |
| Transcript Mapping | "map transcript", "mapped transcript" | `map-transcript` |
| Insights Saturation | "saturation", "saturate insights" | `saturate-insights` with an absolute canonical `mapped-transcript.md` path |

## Available Skills
- **[Transcribe Audios](./skills/transcribe-audios/SKILL.md)**
- **[Create Questionnaire Table](./skills/create-questionnaire-table/SKILL.md)**
- **[Map Transcript](./skills/map-transcript/SKILL.md)**
- **[Saturate Insights](./skills/saturate-insights/SKILL.md)**

## Input & Output
**Input**: Natural language request, a folder path, and an `api_keys` mapping
provided by the parent for the full workflow. Transcription requires
`api_keys.ELEVENLABS_API_KEY`; isolated
`saturate-insights` requests require the absolute canonical
`Interview/mapped-transcript.md` path and no API key.
**Output**: Skill execution result (e.g., status, generated file paths).

## Environment Access (.env)
- **Allowed to access `.env`**: `false`
- **ELEVENLABS_API_KEY**: Received from `ux-research` and injected only into
  `transcribe-audios`.

## Sequence Diagram
```mermaid
sequenceDiagram
    autonumber
    actor User
    participant FO as Father Orchestrator
    participant UXI as UX Interview
    participant CQT as Create Questionnaire Table
    participant STT as ElevenLabs Transcribe
    participant MT as Map Transcript
    participant SA as Saturate Insights

    User->>FO: Start UX research workflow
    FO->>UXI: Route with folder_path and ELEVENLABS_API_KEY
    activate UXI
    
    UXI->>UXI: 1. Folder Creation & Move Inputs (Interview/)
    UXI->>CQT: 2. Questionnaire Extraction
    CQT-->>UXI: Return full-questionnaire.md
    UXI-->>User: 3. Ask for approval
    User->>UXI: Approve
    
    UXI->>UXI: 4a. Live ElevenLabs Speech to Text docs preflight
    alt Docs unavailable or contract changed
        UXI-->>User: Halt and request docs review/update
    else Docs verified
    UXI->>STT: 4. Inject received key and transcribe
    
    alt Transcription Error
        STT-->>UXI: Return error
        UXI-->>User: Halt & show error code
    else Success
        STT-->>UXI: Return transcripts
        UXI-->>User: 5. Ask for approval
        User->>UXI: Approve

        UXI->>MT: 6. Prepare, bounded-map, validate, finalize
        alt Partial Mapping
            MT-->>UXI: Return PARTIAL_MAPPING; canonical unchanged
            UXI-->>User: Halt with per-transcript failures
        else Complete Mapping
            MT-->>UXI: Return canonical + review outputs
            UXI-->>User: 7. Ask for approval
            User->>UXI: Approve

            UXI->>SA: 8. Pass canonical mapped-transcript.md only
            Note over SA: Verify mapping manifest,<br/>extract ≤4 at a time,<br/>ground and consolidate evidence
            SA-->>UXI: Return atomic insights set + review manifest
            UXI-->>User: 9. Ask for approval
            User->>UXI: Approve
        end
    end
    end
    UXI-->>FO: Return result
    deactivate UXI
    FO-->>User: Respond
```

## Error Handling
| Error Scenario | Handling |
| --- | --- |
| `UNKNOWN_INTENT` | Ask for clarification or list capabilities. |
| `SKILL_FAILURE` | Log and return graceful failure message. |
| `INVALID_INPUT` | Return validation error for missing folder/format. |
| `MISSING_API_KEY` | Halt before transcription and ask `ux-research` to provide `ELEVENLABS_API_KEY` from the workspace `.env`. |
| `PARTIAL_MAPPING` | Halt before insights, preserve the prior canonical mapped transcript, and show per-transcript failures. |
| `RETRY_EXHAUSTED` | Halt mapping after the controller limit and ask the user to inspect the recorded diagnostic. |
| `SOURCE_TIMESTAMP_NOT_FOUND` / `NON_VERBATIM_RESPONSE` | Retry the affected mapped row using the complete timestamped source turn exactly as written in that interviewee's transcript. |
| `UPSTREAM_MAPPING_NOT_SUCCESS` | Halt insights; only a complete current canonical mapping may continue. |
| `UPSTREAM_SIGNATURE_MISMATCH` | Rerun map-transcript preflight; do not consume a modified or stale canonical file. |
| `PARTIAL_EXTRACTION` / `PARTIAL_CONSOLIDATION` | Halt insights publication, preserve the last-known-good outputs, and show per-task diagnostics. |
| `EXTRACTION_VALIDATION_FAILED` / `CONSOLIDATION_VALIDATION_FAILED` | Retry with controller diagnostics up to the configured maximum; never publish ungrounded evidence. |
| `MISSING_DEPENDENCY` / `ATOMIC_PROMOTION_ERROR` | Preserve existing insight outputs and return the structured renderer or publication failure. |
