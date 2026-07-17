import asyncio
import os
import sys
import time
from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig

PLAN_PATH = "/Users/madebynham/.gemini/antigravity/brain/24d95e8d-b198-4597-8f94-6ba181dd1f62/implementation_plan.md"

PROMPT = """
You are an expert software architect assisting in creating a detailed implementation plan for a new skill in the `ux-cjm` workflow.
We want to create a new skill named `interpret-phase` before the `extract-map` skill.

Here are the requirements for `interpret-phase`:
1. Input: A dictionary containing `folder_path` (pointing to the project folder), which reads the 5 generated `extracted-<phase>.md` files in the `Journey Map` folder.
2. Output: Generates 5 separate table files (`interpret-awareness.md`, `interpret-consideration.md`, `interpret-decision-making.md`, `interpret-usage.md`, and `interpret-advocacy.md`) in the `Journey Map/` folder, and returns a success status dictionary.
3. Content structure: Each `interpret-<phase>.md` file must be a markdown table with exactly the following rows (dimensions):
   - Stage Goal
   - Stage Touchpoints
   - Stage Actions
   - Stage Pain Points
   - Stage Emotion (1-5)
   - Stage Opportunities & Metrics
4. API Key: Use the built-in Antigravity AI (no external API Key required).
5. Code structure: Follow the skill structure template. This includes:
   - `.agents/workflows/ux-cjm/skills/interpret-phase/SKILL.md`
   - `.agents/workflows/ux-cjm/skills/interpret-phase/scripts/interpret_phase.py` (which implements the execution logic using built-in AI)
   - `.agents/workflows/ux-cjm/skills/interpret-phase/tests/test_interpret_phase.py` (which contains unit tests with mocks)
6. Additional updates:
   - Update `.agents/workflows/ux-cjm/ORCHESTRATOR.md` to add `interpret-phase` as a step between `extract-phases` and `extract-map`.
   - Update the `extract-map` skill (`.agents/workflows/ux-cjm/skills/extract-map/scripts/extract_map.py` and its tests and SKILL.md) to read/map from `interpret-*.md` instead of `extracted-*.md`.
   - Update `.agents/workflows/ux-cjm/tests/test_e2e_pipeline.py` to test the new end-to-end pipeline (extract-phases -> interpret-phase -> extract-map).

Please write a detailed implementation_plan.md matching the template format below. Do not output anything else besides the file content.

Format:
```markdown
# [Goal Description]

...

## User Review Required

...

## Open Questions

...

## Proposed Changes

...

## Verification Plan

...
```
"""

async def main():
    config = LocalAgentConfig(
        system_instructions="You are a senior system planner. Generate only the markdown content of the implementation_plan.md. Do not wrap in extra explanation text.",
        capabilities=CapabilitiesConfig()
    )
    
    max_retries = 5
    delay = 10
    
    for attempt in range(1, max_retries + 1):
        try:
            print(f"Attempt {attempt} of {max_retries}...")
            async with Agent(config) as agent:
                response = await agent.chat(PROMPT)
                full_text = ""
                async for token in response:
                    full_text += token
                    
                import re
                match = re.search(r'```markdown\n(.*?)\n```', full_text, re.DOTALL)
                if match:
                    clean_content = match.group(1).strip()
                else:
                    clean_content = full_text.strip()
                    
                os.makedirs(os.path.dirname(PLAN_PATH), exist_ok=True)
                with open(PLAN_PATH, "w", encoding="utf-8") as f:
                    f.write(clean_content)
                print("Plan written successfully to:", PLAN_PATH)
                return
        except Exception as e:
            print(f"Attempt {attempt} failed with error: {e}")
            if attempt < max_retries:
                print(f"Waiting {delay} seconds before retry...")
                await asyncio.sleep(delay)
                delay += 15
            else:
                print("Max retries reached. Exiting with failure.")
                sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
