---
name: UX CJM
description: Automates workflows for Customer Journey Map generation, parsing transcript data and extracting phases.
---

# UX CJM Orchestrator

## Description

The UX CJM Orchestrator manages the workflow automation for extracting and organizing customer journey phases from raw transcript data, and assembling them into a final journey map. It parses mapped transcripts, routes the data to appropriate extraction skills to build detailed phase-based documentation (Awareness, Consideration, Decision Making, Usage, Advocacy), and finally maps them into a unified customer journey map.

## Routing Logic & Execution Flow

0. **Dependency Verification**: Before executing the first skill, the orchestrator runs the package validation script `.agents/scripts/check_libraries.py` to ensure all required external packages (e.g. `pytest`, `matplotlib`) are installed and up to date.
1. **Phase Extraction**: When a mapped transcript is provided, the orchestrator routes the request to the `extract-phases` skill, which sequentially parses the "Theme" column and generates individual markdown files for each phase.
2. **Phase Interpretation**: The orchestrator routes the request to the `interpret-phases` skill, which uses the built-in AI to sequentially interpret each extracted phase document into a formatted table containing the phase's goal, touchpoints, actions, pain points, emotion, and opportunities.
3. **Phase Mapping**: Once the phases are interpreted, the orchestrator triggers the `extract-map` skill to deterministically compile these interpreted files into a final `journey-map.md` using a programmatic Python script, ensuring 100% accuracy and zero AI hallucination.

**Execution Rule:** When a skill in its flow completes its task and generates an output, the orchestrator MUST pause and ask the user for approval. If the user approves and no changes are needed, the orchestrator then executes the next skill in the sequence.


## Available Skills

This orchestrator manages and routes requests to the following skills:

- **[extract-phases](./skills/extract-phases/SKILL.md)**: Extracts rows from a mapped transcript into 5 separate phase files based on the "Theme" column.
- **[interpret-phases](./skills/interpret-phases/SKILL.md)**: Interprets extracted phase documents sequentially using built-in AI and creates formatted Markdown tables for each phase.
- **[extract-map](./skills/extract-map/SKILL.md)**: Maps the individually interpreted phase files deterministically into a final `journey-map.md` template using a Python script without AI.

## Input

- **Type**: `dict`
- **Format**: Requires a `folder_path` pointing to the directory containing the `mapped-transcript.md`.
- **Location**: `request_body`
- **Examples**:

  **Example 1** — Standard user request:
  ```json
  {
    "folder_path": "/path/to/project_folder/"
  }
  ```

## Output

- **Type**: `dict`
- **Format**: Returns the status and paths to the extracted phase files.
- **Location**: `response_body`
- **Examples**:

  **Example 1** — Successful orchestration:
  ```json
  {
    "status": "success",
    "message": "Extracted 5 phases and mapped to journey-map.md successfully.",
    "data": {
      "skill_executed": "extract-map",
      "result_paths": [
        "/path/to/project_folder/Journey Map/journey-map.md"
      ]
    }
  }
  ```

## Environment Access (.env)

- **Allowed to access `father-orchestrator/.env`**: `false`

## Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Orchestrator
    participant Skill1 as extract-phases
    participant Skill2 as interpret-phases
    participant Skill3 as extract-map

    User->>Orchestrator: Send request (folder_path)
    activate Orchestrator
    Note over Orchestrator: Route to extract-phases

    Orchestrator->>Skill1: Execute Skill (folder_path)
    activate Skill1
    Skill1-->>Orchestrator: Return Extracted Files
    deactivate Skill1
    
    Note over Orchestrator: User approves to continue

    Orchestrator->>Skill2: Execute Skill (folder_path)
    activate Skill2
    Skill2-->>Orchestrator: Return Interpreted Tables
    deactivate Skill2
    
    Note over Orchestrator: User approves to continue

    Orchestrator->>Skill3: Execute Skill (folder_path)
    activate Skill3
    Skill3-->>Orchestrator: Return Generated Journey Map
    deactivate Skill3

    Orchestrator-->>User: Return final response (journey-map.md)
    deactivate Orchestrator
```

## Error Handling & Fallbacks

| Error Scenario | Message | Fallback Behavior |
| --- | --- | --- |
| `UNKNOWN_INTENT` | Could not determine which skill to use. | Ask the user for clarification or provide a list of available capabilities. |
| `SKILL_FAILURE` | The invoked skill returned an error. | Catch the error, log it, and return a graceful failure message to the user, potentially suggesting a retry. |
| `INVALID_INPUT` | The incoming request is malformed. | Return a validation error specifying the required format. |
