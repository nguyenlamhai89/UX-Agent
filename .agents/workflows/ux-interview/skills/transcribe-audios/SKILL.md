---
name: transcribe-audios
description: Transcribes audio files in a folder into Markdown files using ElevenLabs Speech-to-Text or Google Gemini as a fallback.
---

# Transcribe Audios

## Description

The `transcribe-audios` skill transcribes interview audio files into Markdown with speaker diarization. It supports two providers: **ElevenLabs** (primary, using the `speech_to_text.convert` API with the Scribe v2 model) and **Google Gemini** (fallback). It traverses the `Interview` subfolder of an input folder for audio files (e.g., `.mp3`, `.m4a`, `.qta`) and outputs corresponding `.md` files. At least one API key (`ELEVENLABS_API_KEY` or `GEMINI_API_KEY`) must be provided. When both keys are available, ElevenLabs is tried first; on failure, Gemini is used automatically.

The orchestrator should trigger this skill when the user requests audio transcription, converting speech to text, or generating interview transcripts.

## Input

- **Type**: `dict`
- **Format**:
  - `folder_path` (string, required): The absolute path to the directory containing audio files.
  - `keyterms` (list of strings, optional): Specific keywords or vocabulary to prioritize during transcription.
  - `max_workers` (integer, optional): Maximum concurrent uploads; defaults to 5.
  - `max_file_size_mb` (integer, optional): Per-file upload limit; defaults to 200 MB.
  - `max_retries` (integer, optional): Retries for transient API failures; defaults to 3.
- **Environment**: The parent `ux-research` orchestrator reads `.env` and passes
  `ELEVENLABS_API_KEY` and/or `GEMINI_API_KEY` to `ux-interview`. The child
  orchestrator injects the received keys into this skill process. The skill
  never reads `.env` directly. At least one transcription key is required.
- **Location**: `request_body`
- **Input File(s)**:
  - `Interview/*.mp3`, `Interview/*.m4a`, `Interview/*.qta` — Raw audio files containing interviews or recordings in the `Interview` subfolder.
- **Examples**:

  **Example 1** — Transcription request:
  ```json
  {
    "folder_path": "/Users/madebynham/Desktop/interviews/round-1",
    "api_key": "YOUR_ELEVENLABS_API_KEY",
    "keyterms": ["ux research", "wireframes", "prototyping"]
  }
  ```

## Output

- **Type**: `dict`
- **Format**: 
  - Success: `status: "success"` and `data` containing `transcripts` (sorted list of `audio_file` and `output_file`) and `total`.
  - Failure: `status: "error"`, `error_code`, `message`, `errors` (per-file code and message), and `successful_transcripts` when applicable.
- **Location**: `file_path` — The generated files are saved to an `Interview` subfolder within the provided folder.
- **Output File(s)**:
  - `Interview/transcript_<audio_name>.md` — The generated markdown transcript files.
- **Examples**:

  **Example 1** — Successful execution:
  ```json
  {
    "status": "success",
    "data": {
      "transcripts": [
        {
          "audio_file": "interview-john.mp3",
          "output_file": "/Users/madebynham/Desktop/transcripts/Interview/transcript_interview-john.md"
        }
      ],
      "total": 1
    }
  }
  ```

- **Specific format output (e.g., Markdown template)**:
  ```markdown
  # INTERVIEW TRANSCRIPT: [AUDIO FILE NAME]
  **[00:00] [Host]** <br>
  Transcription content
  **[00:25] [Interviewee Name]** <br>
  Transcription content
  ```

## API Key

| Field | Value | Notes |
| --- | --- | --- |
| **Key** | `ELEVENLABS_API_KEY` | Primary provider. Loaded by `ux-research`, delegated to `ux-interview`, and injected into this skill process. |
| **Key** | `GEMINI_API_KEY` | Fallback provider. Same delegation path. Used automatically when ElevenLabs fails or its key is absent. |

> **Note**: At least one of `ELEVENLABS_API_KEY` or `GEMINI_API_KEY` must be
> provided. Skills MUST NOT read API keys directly from `.env`. Only
> `ux-research` reads the workspace `.env`; `ux-interview` receives the required
> keys and injects them into this skill process. Never hardcode, log, or write
> keys to output files. When both keys are available, ElevenLabs is the primary
> provider and Gemini serves as an automatic fallback on failure.

## Custom Instructions

- **Execution Method**: The orchestrator supplies the environment variable, then runs: `python3 .agents/workflows/ux-interview/skills/transcribe-audios/scripts/transcribe.py <folder_path> [--keyterms "term1,term2"] [--max-workers 5] [--max-file-size-mb 200] [--max-retries 3]`.
- The script automatically writes the `transcript_<filename>.md` file in the same `Interview` directory as the input audio file.

## Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Orchestrator
    participant Skill
    participant ElevenLabsAPI
    participant GeminiAPI

    User->>Orchestrator: "Transcribe the audio files in the Interview folder"
    activate Orchestrator
    
    Orchestrator->>Skill: Execute `transcribe.py` with folder_path, api_keys, & optional keyterms
    activate Skill
    
    loop For each audio file
        alt ElevenLabs key available
            Skill->>ElevenLabsAPI: Send audio data
            activate ElevenLabsAPI
            ElevenLabsAPI-->>Skill: Return transcription text
            deactivate ElevenLabsAPI
        else ElevenLabs fails or key absent, Gemini key available
            Skill->>GeminiAPI: Upload audio & prompt
            activate GeminiAPI
            GeminiAPI-->>Skill: Return transcription text
            deactivate GeminiAPI
        end
        Skill->>Skill: Write `transcript_<filename>.md`
    end
    
    alt Success
        Skill-->>Orchestrator: Return JSON with list of transcript files
    else API Error
        Skill-->>Orchestrator: Return error JSON
    end
    deactivate Skill
    
    Orchestrator-->>User: Respond with transcription results
    deactivate Orchestrator
```

## Error Handling & Fallbacks

| Error Code | Message | Fallback Behavior |
| --- | --- | --- |
| `NO_AUDIO_FILES` | No supported audio files found in the specified folder. | Inform the user that the folder is empty or contains no supported audio files. |
| `MISSING_API_KEY` | Neither `ELEVENLABS_API_KEY` nor `GEMINI_API_KEY` was injected by `ux-interview`. | Halt and ask the parent workflow to load at least one transcription key from `.env` and pass it through the authorized chain. |
| `INVALID_INPUT` | The supplied folder does not exist. | Return the validation error without calling the API. |
| `INPUT_TOO_LARGE` | An audio file exceeds `--max-file-size-mb`. | Increase the configured limit only when the API account supports the upload. |
| `EMPTY_TRANSCRIPT` | The API response contains no usable text. | Return a per-file failure and do not create a transcript. |
| `API_REQUEST_ERROR` | The API rejected a terminal request, such as invalid credentials. | Do not retry; return the per-file error. |
| `API_RETRYABLE_ERROR` | A network, rate-limit, or server failure persisted through retries. | Retry with exponential backoff, jitter, and `Retry-After` where available. |
| `FUTURE_ERROR` / `FILE_PROCESSING_ERROR` | Unexpected worker or local file-processing failure. | Return the affected file and continue the remaining batch. |
| `PARTIAL_FAILURE` / `TRANSCRIPTION_FAILED` | One or all files failed. | Return successful transcripts alongside detailed errors. |

## Known Bugs & Resolutions

> **Agent Rule (Error Handling & Bug Documentation):** In the future, when this skill encounters an error during input receiving, processing, or output generation, the AI agent must first propose a solution to the user. If the user agrees, the AI agent will fix the error. If the error is successfully fixed, the AI agent must update this 'Known Bugs & Resolutions' section with the bug, cause, and resolution.

| Bug / Error | Cause | Resolution |
| --- | --- | --- |
| `TypeError: convert() got an unexpected keyword argument 'tag_audio_events'` | The ElevenLabs Python SDK `speech_to_text.convert` method does not accept the parameter `tag_audio_events`. | Removed the `tag_audio_events=True` parameter from the API call. |
| Words joined without spaces (e.g., `helloworld`) | ElevenLabs STT `word.text` does not include trailing spaces, causing simple string concatenation to mash words together. | Updated the concatenation logic to prepend a space: `current_text += " " + word.text.strip()`. |
| API 400 Bad Request error for empty keyterms | Passing an empty string `--keyterms ""` resulted in an array `[""]` being sent to the API, which may be invalid. | Added empty string filtering during parsing: `[k.strip() for k in args.keyterms.split(',') if k.strip()]`. |
| Invalid or partially written transcripts were skipped on a rerun | Skip logic checked only for file existence, so a failed write could prevent recovery. | Validate the transcript structure and write through a temporary sibling file before atomically replacing the final file. |
| Skill validation rejected the metadata name | The frontmatter used the display label `ElevenLabs Transcribe`, which was not lowercase hyphen-case. | Changed the metadata name to `elevenlabs-transcribe` and retained the readable Markdown heading. |

## Performance Improvement Solutions

**⚡ Execution Efficiency**
- [x] Use `concurrent.futures.ThreadPoolExecutor` to process multiple audio files in parallel.
- [x] Consider streaming audio files if the ElevenLabs API supports it, or implement chunking for very large files.
- [ ] Implement streaming or chunked file reading for audio files larger than a configurable threshold (e.g., 100MB) to reduce peak memory usage when processing multiple large files concurrently with `ThreadPoolExecutor`.
- [x] Make the transcription worker count and rate-limit cap configurable, with conservative defaults for large files.

**🎯 Output Quality & Accuracy**
- [x] Align the documented JSON output contract with the CLI's `data` envelope and partial-failure fields.
- [x] Reject empty transcription text before writing a completed transcript.

**🔗 Workflow Fit**
- [x] Align API-key documentation with the actual environment-variable contract; implement Gemini fallback when ElevenLabs is unavailable.
- [x] Validate existing transcripts before skipping them, use atomic writes, and return results in filename order.

**🛡️ Reliability & Error Handling**
- [x] Catch transcription exceptions per file and continue processing the remaining files instead of exiting immediately.
- [x] Implement an exponential backoff retry mechanism around the ElevenLabs API call for robustness.
- [x] Classify retryable API failures, honor `Retry-After` where available, add jitter, and do not retry invalid credentials or requests.
- [x] Catch unexpected future-result failures and return documented per-file error codes.
- [x] Add regression tests for documented word-spacing and empty-keyterms bugs.

**💰 Cost & Scalability**
- [x] Implement concurrent execution to improve scaling behavior when processing multiple audio files.
- [x] Add unit tests covering ElevenLabs API failure scenarios and edge cases (e.g. empty files).
- [x] Add tests for keyterms parsing, timestamps, diarized-word output, and empty transcription content.
- [x] Add a dedicated regression test for unexpected future-result failures.
