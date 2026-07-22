---
name: Create Questionnaire Table
description: Extracts a question table from an image (PNG/JPG) in a folder and outputs a structured full-questionnaire.md file with fully expanded rows.
---

# Create Questionnaire Table

## Description

This skill extracts a question table from a single image file (PNG or JPG) located in a folder and converts it into a structured Markdown table saved as `full-questionnaire.md`. The agent uses its built-in vision capability to read the image and identify table rows, then formats them into a 4-column expanded table.

The orchestrator should trigger this skill when:
- The user wants to convert a question table image into a Markdown file.
- The user provides a folder path containing a question table image.
- Keywords such as "questionnaire", "question table", "extract table from image", "convert table image to markdown" are detected.

**Prerequisites:**
- The input folder must exist, and its `Interview` subfolder must contain exactly one image file (`.png` or `.jpg`/`.jpeg`).

## Input

- **Type**: `dict`
- **Format**:
  - `folder_path` (string, **required**) — Absolute path to a local directory (e.g., project root).
- **Location**: `request_body`
- **Input File(s)**:
  - `Interview/<image>.png` / `Interview/<image>.jpg` / `Interview/<image>.jpeg` — A single question table image file in the `Interview` subfolder.
- **Supported file types**: `.png`, `.jpg`, `.jpeg` only. Other files in the folder are ignored.
- **Examples**:

  **Example 1** — Folder with a single PNG:
  ```json
  {
    "folder_path": "/Users/madebynham/Desktop/questionnaire-images"
  }
  ```

## Output

- **Type**: `dict`
- **Format**:
  - `status` (string) — `"success"` or `"error"`.
  - `image_file` (string) — Original image filename that was processed.
  - `output_file` (string) — Absolute path to the generated `full-questionnaire.md` file.
- **Location**: `file_path` — The `full-questionnaire.md` file is saved inside an `Interview` subfolder within the folder the user provided.
- **Output File(s)**:
  - `Interview/full-questionnaire.md` — The structured questionnaire table with 4 columns (`#`, `Theme`, `Question`, `Observed Variable`).
- **Examples**:

  **Example 1** — Successful extraction:
  ```json
  {
    "status": "success",
    "image_file": "question-table.png",
    "output_file": "/Users/madebynham/Desktop/questionnaire-images/Interview/full-questionnaire.md"
  }
  ```

- **Specific format output (e.g., Markdown template)**:

  The output file always contains a table with exactly **4 columns**: `#`, `Theme`, `Question`, `Observed Variable`.

  Rows are **fully expanded** — no merged cells. If 1 question has many observed variables, each observed variable gets its own row. The `#` is the **question's order number** — all rows with the same question content share the same `#`. The number increments only when the question changes.

  ```markdown
  | # | Theme | Question | Observed Variable |
  |---|-------|----------|-------------------|
  | 1 | Warm Up | Please introduce yourself | Name |
  | 1 | Warm Up | Please introduce yourself | Age |
  | 2 | Warm Up | How was your day today | Journey |
  | 2 | Warm Up | How was your day today | Pain Point |
  | 3 | Product Experience | What do you think about X | First Impression |
  | 3 | Product Experience | What do you think about X | Usability |
  | 4 | Wrap Up | Any final thoughts | Suggestion |
  | 4 | Wrap Up | Any final thoughts | Overall Feeling |
  | 5 | Wrap Up | Would you recommend this | Likelihood |
  ```

> **Note**: The table structure is always 4 columns regardless of the source image layout. The agent will interpret the image content and map it to the `#`, `Theme`, `Question`, and `Observed Variable` columns.
>
> **Important**: The `#` column is the **question's order number**. All rows with the same question content MUST share the same `#` value. The number only increments when the question changes.


## Custom Instructions

- **Execution Method**: This skill is executed entirely by the Antigravity AI agent — no external scripts or API calls. The agent follows these steps directly:
  1. **Check for existing file**: Check if `Interview/full-questionnaire.md` already exists in `folder_path`. If it does, skip processing and return success to save time and API costs.
  2. **Scan the folder** at the provided `folder_path/Interview` for image files (`.png`, `.jpg`, `.jpeg`). 
  3. **Process images**: If there are multiple images (multi-page questionnaire), view them in order. 
  4. **Extract all table data** from the images. Identify each topic, its questions, and their observed variables. If multiple pages, concatenate the tables.
  5. **Assign the `#` (order number) by question** — all rows with the same question content share the same number. The number increments only when the question changes. For multi-page, ensure numbering is continuous across pages.
  6. **Expand all rows** so that every unique combination of (number, topic, question, observed variable) is a separate row. Never merge cells.
  7. **Format as a Markdown table** with exactly 4 columns: `#`, `Theme`, `Question`, `Observed Variable`. Limit output entirely to the `# Questionnaire` heading and the table — absolutely no preamble, explanations, or markdown code fences.
  8. **Write the result** to `<folder_path>/Interview/full-questionnaire.md` using the `write_to_file` tool.
  9. **Self-verify**: Re-read the generated `Interview/full-questionnaire.md` and visually verify it against the original image.
  10. **Automated Validation**: Run the Python script `scripts/validate_questionnaire.py <folder_path>/Interview/full-questionnaire.md`. 
      - If the script returns success (exit code 0), return success.
      - If the script returns an error (exit code 1), delete the partially written/invalid `Interview/full-questionnaire.md` file immediately to prevent downstream errors. Read the image again and retry up to 2 times. If it still fails, return the `UNREADABLE_IMAGE` error.
- If the image contains text in Vietnamese, preserve the original Vietnamese text in the output.
- Do not add any extra content to the markdown file beyond a level-1 heading (`# Questionnaire`) and the table itself.
- Do not wrap the table in code fences.
- The `#` column must be auto-generated (starting from 1 and incrementing only when the question text changes) if not explicitly present in the image. All rows with identical question content MUST share the same `#` value.
- The `Theme` column is optional. If the image lacks a Theme column but contains Question and Observed Variable columns, its cells must be left blank (empty string `""`) in the Markdown table, and do not raise a `STRUCTURE_MISMATCH` error.
- All cell contents in the generated Markdown table must be cleaned as single-line plain text strings. Remove any raw newlines (`\n`) or HTML break tags (`<br>`) within cells to ensure the Markdown table structure is not broken.
- The `Question` and `Observed Variable` data are mandatory. If the image lacks data to map to these mandatory columns, halt processing and remind the user to check and upload the image again.
- Clean up — Ensure that any temporary files created during processing (e.g., intermediate files, temporary copies) are deleted immediately after the skill completes its task.

## Sequence Diagram

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Orchestrator
    participant Skill as Create Questionnaire Table
    participant FS as File System
    participant Script as validate_questionnaire.py

    User->>Orchestrator: Send request with folder_path
    activate Orchestrator
    Orchestrator->>Skill: Execute ({"folder_path": "..."})
    activate Skill

    Skill->>FS: Check if full-questionnaire.md exists
    alt Exists
        Skill-->>Orchestrator: Return success (skipped)
    else Does not exist
        Skill->>FS: Scan folder for .png / .jpg files
        FS-->>Skill: Return list of image files

        alt No image files found
            Skill-->>Orchestrator: Return error (NO_IMAGE_FILES)
        else Image(s) found
            loop Up to 3 attempts
                Skill->>FS: Read image files
                Skill->>FS: Write full-questionnaire.md
                Skill->>Script: Run validation
                Script-->>Skill: Return exit code 0 or 1
                alt Exit Code 0 (Success)
                    Skill-->>Orchestrator: Return success + output path
                    break
                else Exit Code 1 (Error)
                    Skill->>FS: Delete invalid full-questionnaire.md
                    Note over Skill: Retry extraction
                end
            end
            alt Still failing after 3 attempts
                Skill-->>Orchestrator: Return error (UNREADABLE_IMAGE)
            end
        end
    end
    deactivate Skill
    Orchestrator-->>User: Respond with result
    deactivate Orchestrator
```

## Error Handling & Fallbacks

| Error Code | Message | Fallback Behavior |
| --- | --- | --- |
| `INVALID_INPUT` | The input folder path is missing or does not exist. | Return a clear validation error to the user. |
| `NO_IMAGE_FILES` | No `.png` or `.jpg` files found in the specified folder. | Return an informative message listing supported formats. |
| `UNREADABLE_IMAGE` | The image could not be interpreted, does not contain a recognizable table, or failed validation after 3 attempts. | Return a friendly error asking the user to provide a clearer image. |
| `STRUCTURE_MISMATCH` | The image does not contain recognizable columns for Question and Observed Variable. | Remind the user to check the image structure and upload it again. |
| `WRITE_FAILURE` | Could not write to the file system. | Check permissions or disk space and alert user. |

## Known Bugs & Resolutions

<!-- List any past bugs or errors encountered during the development or execution of this skill, and explain how they were resolved. This acts as a knowledge base for future maintenance. -->

> **Agent Rule (Error Handling & Bug Documentation):** In the future, when this skill encounters an error during input receiving, processing, or output generation, the AI agent must first propose a solution to the user. If the user agrees, the AI agent will fix the error. If the error is successfully fixed, the AI agent must update this 'Known Bugs & Resolutions' section with the bug, cause, and resolution.

| Bug / Error | Cause | Resolution |
| --- | --- | --- |

## Performance Improvement Solutions

<!-- This section is automatically populated and updated by the analyze-skill. It contains a checklist of actionable solutions to improve this skill's performance across various criteria. -->

**⚡ Execution Efficiency**
- [x] Add explicit instruction in SKILL.md to limit AI output to only the heading and table — no preamble, explanation, or code fences — to minimize output tokens.

**🎯 Output Quality & Accuracy**
- [x] Create a Python validation script (`scripts/validate_questionnaire.py`) that checks the generated `full-questionnaire.md` for: correct column count (4), non-empty Question and Observed Variable columns, consistent `#` numbering, and proper Markdown table syntax.
- [x] After writing `full-questionnaire.md`, run the validation script to enforce the 4-column format, reject tables with merged cells or broken rows, and alert the user if the output is malformed.
- [x] Add an instruction in SKILL.md telling the AI to re-read the generated `full-questionnaire.md` after writing it and verify it against the original image before reporting success.

**🛡️ Reliability & Error Handling**
- [x] Add a `WRITE_FAILURE` error code to the error handling table for cases where the file system write fails (e.g., permission denied, disk full).
- [x] Add explicit instructions in SKILL.md for the AI to delete any partially written `full-questionnaire.md` file if an error occurs mid-processing, preventing downstream skills from consuming malformed data.
- [x] Add explicit retry instruction: if first extraction attempt produces a table that fails validation, re-read the image and retry up to 2 times before returning `UNREADABLE_IMAGE` error.
- [x] Create a `tests/` directory with `test_validate_questionnaire.py` that tests the validation script against known good and bad table formats.

**💰 Cost & Scalability**
- [x] Add instruction to skip processing if `full-questionnaire.md` already exists in the folder, avoiding redundant AI vision calls.
- [x] Add instructions for handling multi-page questionnaires: if more than one image is detected, process them in order and concatenate the tables, adjusting `#` numbering to be continuous across pages.
- [x] Create `tests/test_validate_questionnaire.py` with test cases covering: valid 4-column table, missing columns, inconsistent numbering, empty Question/Observed Variable cells, and tables with HTML/newline artifacts.

**⚡ Execution Efficiency**
- [ ] Sort image paths deterministically and state a bounded multi-page input limit.
- [ ] Define maximum image count and file-size limits with a clear validation error.

**🎯 Output Quality & Accuracy**
- [ ] Align the `image_file` result contract with multi-page processing and return final validator details on terminal failure.
- [ ] Require exactly one permitted heading/table block and reject or escape unescaped pipe characters in table cells.
- [ ] Add a self-verification checklist for page coverage, row count, question sequence, and mandatory fields.
- [ ] Add fixtures for multi-page order, Vietnamese text, literal pipes, extra prose, and malformed separators.

**🔗 Workflow Fit**
- [ ] Align single-image prerequisites, multi-page instructions, and output schema.
- [ ] Validate an existing `full-questionnaire.md` before skipping; delete and regenerate it if invalid.

**🛡️ Reliability & Error Handling**
- [ ] Handle validator runtime errors and bounded-input failures with cleanup and actionable error codes.
- [ ] Retry only image interpretation or structural-validation failures; fail immediately for filesystem and input errors.
- [ ] Add regression tests for invalid cached output and Markdown edge cases, then document confirmed fixes.

**💰 Cost & Scalability**
- [ ] Set input limits and process sorted pages in bounded batches with progress reporting.
- [ ] Add tests for no table, invalid headers, extra content, literal pipes, duplicate tables, and CLI exit codes.
