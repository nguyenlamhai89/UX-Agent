---
name: extract-phases
description: Extracts rows for 5 different phases from a mapped transcript into separate markdown files.
---

# extract-phases

## Description

The `extract-phases` skill parses a `mapped-transcript.md` file and extracts rows that match specific UX phases based on the "Theme" column. It creates a `Journey Map` folder in the given directory and generates 5 separate markdown files (`extracted-awareness.md`, `extracted-consideration.md`, `extracted-decision-making.md`, `extracted-usage.md`, and `extracted-advocacy.md`) while preserving the original table headers.

This skill is invoked when the orchestrator needs to break down a comprehensive mapped transcript into individual phases for further analysis or Journey Map visualization.

## Input

- **Type**: `dict`
- **Format**: Must contain a `folder_path` key.
- **Location**: `request_body`
- **Input File(s)**:
  - `mapped-transcript.md` — The parsed transcript table containing a "Theme" column.
- **Examples**:

  **Example 1** — Standard user request:
  ```json
  {
    "folder_path": "/path/to/project/folder/"
  }
  ```

## Output

- **Type**: `dict`
- **Format**: Contains a success status and paths to the generated files.
- **Location**: `response_body`
- **Output File(s)** (Created inside the `Journey Map` folder):
  - `Journey Map/extracted-awareness.md` — Rows matching "1. Awareness" or "Awareness"
  - `Journey Map/extracted-consideration.md` — Rows matching "2. Consideration" or "Consideration"
  - `Journey Map/extracted-decision-making.md` — Rows matching "3. Decision Making" or "Decision Making"
  - `Journey Map/extracted-usage.md` — Rows matching "4. Usage" or "Usage"
  - `Journey Map/extracted-advocacy.md` — Rows matching "5. Advocacy" or "Advocacy"
- **Examples**:

  **Example 1** — Single result:
  ```json
  {
    "status": "success",
    "result": "Extracted 5 phases successfully to the provided folder_path."
  }
  ```

## Custom Instructions

- Execute the `extract_all_phases.py` script located in the `scripts/` directory.
- Pass `--folder-path` as an argument.
- Ensure the original `mapped-transcript.md` remains unmodified.
- Ensure the output markdown files have the exact same table headers as the original input file.

## Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Orchestrator
    participant Skill

    User->>Orchestrator: Send request (folder_path)
    activate Orchestrator
    Note over Orchestrator: Parse intent,<br>select best Skill

    Orchestrator->>Skill: Execute (folder_path)
    activate Skill
    
    Note over Skill: Run extract_all_phases.py to generate output files

    alt Success
        Skill->>Orchestrator: Return success status
        deactivate Skill
        Orchestrator->>User: Respond with formatted result
        deactivate Orchestrator
    else Failure
        Skill->>Orchestrator: Return error status and error message
        deactivate Skill
        Orchestrator->>User: Respond with fallback / error message
        deactivate Orchestrator
    end
```

## Error Handling & Fallbacks

| Error Code | Message | Fallback Behavior |
| --- | --- | --- |
| `INVALID_INPUT` | The input is missing `folder_path` or `mapped-transcript.md` does not exist. | Return a clear validation error to the user. |
| `FILE_READ_ERROR` | Unable to read the markdown file. | Ensure file permissions and retry. |
| `PARSE_ERROR` | The markdown table does not have a "Theme" column. | Return an error indicating the format is invalid. |

## Known Bugs & Resolutions

> **Agent Rule (Error Handling & Bug Documentation):** In the future, when this skill encounters an error during input receiving, processing, or output generation, the AI agent must first propose a solution to the user. If the user agrees, the AI agent will fix the error. If the error is successfully fixed, the AI agent must update this 'Known Bugs & Resolutions' section with the bug, cause, and resolution.

| Bug / Error | Cause | Resolution |
| --- | --- | --- |
| `None` | N/A | N/A |

## Performance Improvement Solutions

### ⚡ Execution Efficiency
- [x] **Execution Time:** Refactor to a single script that reads the file once and outputs to all 5 phase files simultaneously.

### 🛡️ Reliability & Error Handling
- [x] **Error Rate:** Add logging or warnings for rows that appear to be part of the table but fail to parse correctly.

### 💰 Cost & Scalability
- [x] **Scaling Behavior:** Consolidate the extraction logic into a single script that routes rows to multiple file handlers simultaneously.
