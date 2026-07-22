---
name: ElevenLabs Transcribe
description: Transcribes audio files in a folder into Markdown files using the ElevenLabs Speech-to-Text API.
---

# ElevenLabs Transcribe

## Description

The `elevenlabs-transcribe` skill is a Python script wrapper around the ElevenLabs Python SDK. It traverses the `Interview` subfolder of an input folder for audio files (e.g., `.mp3`, `.wav`, `.m4a`, `.qta`), uses the ElevenLabs `speech_to_text.convert` API to generate text transcripts with speaker diarization, and outputs the result into corresponding `.md` files within the same `Interview` folder.

The orchestrator should trigger this skill when the user requests audio transcription, converting speech to text, or generating interview transcripts.

## Input

- **Type**: `dict`
- **Format**:
  - `folder_path` (string, required): The absolute path to the directory containing audio files.
  - `keyterms` (list of strings, optional): Specific keywords or vocabulary to prioritize during transcription.
  - `max_workers` (integer, optional): Maximum concurrent uploads; defaults to 5.
  - `max_file_size_mb` (integer, optional): Per-file upload limit; defaults to 100 MB.
  - `max_retries` (integer, optional): Retries for transient API failures; defaults to 3.
- **Environment**: The orchestrator injects `ELEVENLABS_API_KEY` into the skill process. The skill never reads `.env` directly.
- **Location**: `request_body`
- **Input File(s)**:
  - `Interview/*.mp3`, `Interview/*.wav`, `Interview/*.m4a`, `Interview/*.qta` — Raw audio files containing interviews or recordings in the `Interview` subfolder.
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
| **Key** | `ELEVENLABS_API_KEY` | Must match the variable name defined in the orchestrator's environment. |

> **Note**: Skills MUST NOT read API keys directly from the `.env` file. The orchestrator is responsible for injecting `ELEVENLABS_API_KEY` into the skill process. Never hardcode keys in skill files. A missing key returns `MISSING_API_KEY`; there is no built-in-AI transcription fallback.

## Custom Instructions

- **Execution Method**: The orchestrator supplies the environment variable, then runs: `python3 .agents/workflows/ux-transcribe/skills/elevenlabs-transcribe/scripts/transcribe.py <folder_path> [--keyterms "term1,term2"] [--max-workers 5] [--max-file-size-mb 100] [--max-retries 3]`.
- The script automatically writes the `transcript_<filename>.md` file in the same `Interview` directory as the input audio file.

## Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Orchestrator
    participant Skill
    participant ElevenLabsAPI

    User->>Orchestrator: "Transcribe the audio files in the Interview folder"
    activate Orchestrator
    
    Orchestrator->>Skill: Execute `transcribe.py` with folder_path, api_key, & optional keyterms
    activate Skill
    
    loop For each audio file
        Skill->>ElevenLabsAPI: Send audio data
        activate ElevenLabsAPI
        ElevenLabsAPI-->>Skill: Return transcription text
        deactivate ElevenLabsAPI
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
| `MISSING_API_KEY` | The orchestrator did not inject `ELEVENLABS_API_KEY`. | Ask the orchestrator to configure its environment. |
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
- [x] Align API-key documentation with the actual environment-variable contract; remove or implement the stated built-in-AI fallback.
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
- [ ] Add a dedicated regression test for unexpected future-result failures.
