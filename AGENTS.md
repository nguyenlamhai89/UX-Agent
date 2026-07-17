# Agent Behaviors and Rules

## Skill Creation Workflow
Whenever the user wants to create a new skill, you MUST:
1. Ask the user specifically for the exact **Input**, **Output**, and **API Key** requirements (follow the bullet points in the skill template for these sections).
2. If the user indicates they want to use an **API key** in this skill to process, configure the skill to expect this key as an input parameter from the orchestrator. **ONLY orchestrators are allowed to read from the `.env` file; skills MUST NOT access `.env` directly.**
3. Wait for the user's answers.
4. Always create an **implementation plan** (`implementation_plan.md`) describing the files to be created based STRICTLY on the `template/skill` folder structure.
5. Wait for the user's explicit permission/approval before executing the creation of the skill files.

## Template Updates
Whenever the `template/skill` or `template/orchestrator` template changes, you MUST locate all existing skills or orchestrators that were generated using the template and update them to conform to the latest structure and logic of the template.

## Skill Structure
When creating a new skill, if custom code execution is required, always create a `scripts/` folder to store the execution files. Additionally, if unit testing is needed, always create a `tests/` folder with unit tests (e.g. using `pytest` and mocking external APIs) following the patterns established in the elevenlabs-transcribe skill.

## Orchestrator Structure
Each orchestrator folder MUST contain its own `skills/` folder inside it. The skills that belong to an orchestrator live inside that orchestrator's directory. All orchestrators are placed inside the `.agents/workflows/` directory. The folder structure must follow this pattern:
```
.agents/workflows/
  orchestrator-name/
    ORCHESTRATOR.md
    skills/
      skill-name-1/
        SKILL.md
        scripts/   (if needed)
        tests/     (if needed)
      skill-name-2/
        SKILL.md
```

## Testing Skills
Whenever a requirement related to how a skill works is changed (e.g., input, output, logic, data type), you MUST always run all the unit tests of that skill to ensure it still works correctly.

## Bug Documentation
Whenever a skill encounters an error or bug and it is successfully fixed, you MUST document this error and its resolution in the "Known Bugs & Resolutions" section of that skill's `SKILL.md` file. Additionally, you MUST proactively ensure measures are taken (e.g., updating logic, adding checks, or writing tests) so that the skill will not encounter this error again.

## Orchestrator Updates
Whenever a skill inside an orchestrator changes anything (like its inputs, outputs, logic, or rules), you MUST update its corresponding orchestrator to reflect these changes if needed.

## AI Execution for New Skills

1. **Skill Creation Phase (Planning & Execution)**:
   - You MUST strictly write and run a Python script to call the built-in AI whenever you need to create a skill's implementation plan or execute the creation of that skill.
2. **Skill Runtime Phase (Execution/Usage)**:
   - Once the skill is created, its runtime AI engine must be decoupled from the creation phase AI.
   - The skill should be capable of switching its underlying LLM dynamically based on future requirements, whether it uses the system's Built-in AI or any other third-party API keys (e.g., Gemini, OpenAI).

## Fetching Latest Information
Whenever creating a new skill or orchestrator, you MUST always update yourself with the latest information by dynamically fetching and reading the live documentation from `https://antigravity.google/docs/projects`. Do not rely solely on offline references if the user requests the latest capabilities or integrations.

You MUST use the `read_url_content` tool to read the contents of the following official documentation URLs when you need to update information about skill, workflow, and antigravity:

**Core Documentation & Structure**
* **Docs Home:** `https://antigravity.google/docs`
* **Projects:** `https://antigravity.google/docs/projects`
* **Skills Guide:** `https://antigravity.google/docs/skills`
* **Rules Setup Guide:** `https://antigravity.google/docs/rules`
* **Hooks Guide:** `https://antigravity.google/docs/hooks`

**Advanced Features & Integrations**
* **Plugins:** `https://antigravity.google/docs/plugins`
* **Sidecars:** `https://antigravity.google/docs/sidecars`
* **MCP (Model Context Protocol):** `https://antigravity.google/docs/mcp`
* **Browser Automation:** `https://antigravity.google/docs/browser`

**System Administration**
* **Agent Permissions & Security:** `https://antigravity.google/docs/agent-permissions`
* **Changelog:** `https://antigravity.google/changelog`
* **Support & Troubleshooting:** `https://antigravity.google/support`

## HTML Visualizations
Whenever the user requests to visualize HTML, all future templates must strictly follow the Ant Design system and the structure defined in `skills/visualize-insights/template/insight-template.html`. When this template is changed, ensure that the files generating it or following it are also updated accordingly.
- Keep exactly the Overview, Insights, and Journey Map templates (defined in `overview.html`, `insights-saturation.html` / `saturation.html`, and `journey-map.html`) and their sections in the future when compiling the final HTML file.
Additionally, for the Customer Journey Map visualization:
- The Persona navigation tab MUST always be placed right under the Insights tab, and the Journey Map navigation tab right under the Persona tab in the sidebar navigation (without any "Coming soon" section).
- The Stage Emotion (1-5) dimension cells MUST always be rendered as a custom visual component featuring 5 horizontal parallel lines representing ratings from 1 (bottom) to 5 (top) with matching scale label indicators (`1`, `3`, `5`) on both the left and right sides. The corresponding emotion description badge (e.g. `Neutral 😐`, `Positive 🙂`, `Slightly Negative 🙁`) must be centered horizontally on the corresponding line (e.g., at `top: 50%` for a rating of 3), styled with emotion-specific premium borders and background color highlights (without overriding `bg-white`).



## Workflow End-to-End Testing
- **Mandatory test creation**: Whenever a new workflow is created, it MUST include a `tests` folder containing an end-to-end test suite (`tests/test_e2e_pipeline.py`) that sets up mock datasets, executes all skills in the pipeline sequentially, and asserts that the final output files are correctly generated.
- **Automatic execution**: Whenever a new skill is added to any workflow (e.g. `ux-transcribe`, `ux-cjm`) or an existing skill is modified, you MUST automatically run that workflow's end-to-end test suite (e.g. `pytest .agents/workflows/<workflow-name>/tests/test_e2e_pipeline.py`) at the end of the task to ensure the pipeline remains unbroken.


## Dependency Version Checks
Whenever a workflow runs, the agent MUST check the latest version of the libraries used by its skills:
- Run the dependency check script: `python3 .agents/scripts/check_libraries.py` at the start of the workflow run.
- Print warnings and installation/upgrade suggestions if packages are missing or outdated, but do not halt the execution unless a library critical to the immediately executing step is missing.

## Workspace Preservation and Syncing
To ensure the workspace remains fully portable and syncs seamlessly via iCloud:
- **Skills and Workflows**: All new skills, templates, workflows, and orchestrators MUST be created inside the `.agents/` directory of this workspace.
- **Scratch and Temporary Files**: Any temporary test files, scratch scripts, mock datasets, or execution logs generated during development MUST be saved inside the local workspace (e.g., in the workspace root or a local `scratch/` directory) instead of the global application directory.
- **No External Writes**: The agent MUST NOT write project code, configuration settings, or dependencies to directories outside the workspace (such as `/tmp` or `~/.gemini/`) unless explicitly requested by the user.

## GitHub Synchronization
- **Automatic push**: At the end of every task where any files in the workspace are created, modified, or deleted, the agent MUST automatically stage, commit, and push the changes to GitHub (`git add .`, `git commit -m "update: [short summary of changes]"`, `git push origin main`) to ensure the remote repository is always in sync with the local workspace.



