import os
import glob
import asyncio
import re
import argparse
import sys
import json

from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig

def validate_table(table_content: str) -> tuple[bool, str]:
    """Validates the structure of the interpreted phase Markdown table."""
    # Parse rows
    lines = table_content.strip().split("\n")
    table_lines = [l.strip() for l in lines if l.strip().startswith("|")]
    
    if len(table_lines) < 3:
        return False, "Not a valid Markdown table format (missing columns/separator)"
        
    found = {
        "goal": False,
        "touchpoints": False,
        "actions": False,
        "pain points": False,
        "emotion": False,
        "opportunities": False
    }
    
    for line in table_lines[2:]:
        parts = [p.strip() for p in line.split("|")]
        # parts[0] is empty because line starts with '|', parts[1] is Category, parts[2] is Details
        if len(parts) >= 3:
            key = parts[1].strip().lower()
            val = parts[2].strip()
            
            if "goal" in key:
                found["goal"] = True
            elif "touchpoints" in key:
                found["touchpoints"] = True
            elif "actions" in key:
                found["actions"] = True
            elif "pain points" in key:
                found["pain points"] = True
            elif "emotion" in key:
                found["emotion"] = True
                # Check if emotion contains a score from 1 to 5
                match = re.search(r'\b[1-5]\b', val)
                if not match:
                    return False, f"Stage emotion must contain a numeric score from 1-5, got: '{val}'"
            elif "opportunities" in key or "metrics" in key:
                found["opportunities"] = True
                
    missing = [k for k, v in found.items() if not v]
    if missing:
        return False, f"Missing category rows: {', '.join(missing)}"
        
    return True, ""

async def interpret_phases(folder_path: str, force: bool = False):
    # Folder path contract compatibility: support project folder or nested Journey Map folder
    if os.path.basename(folder_path.rstrip(os.sep)) == "Journey Map":
        journey_map_dir = folder_path
    else:
        journey_map_dir = os.path.join(folder_path, "Journey Map")

    if not os.path.exists(journey_map_dir):
        return {"status": "error", "message": f"Directory not found: {journey_map_dir}"}
        
    extracted_files = glob.glob(os.path.join(journey_map_dir, "extracted-*.md"))
    extracted_files.sort()
    
    if not extracted_files:
        return {"status": "error", "message": "No extracted-*.md files found."}

    # 1. Skip Logic: check if all target interpret-*.md files exist and are non-empty
    skip_needed = True
    for file_path in extracted_files:
        phase_name = os.path.basename(file_path).replace("extracted-", "").replace(".md", "")
        interpret_file = os.path.join(journey_map_dir, f"interpret-{phase_name}.md")
        if not os.path.exists(interpret_file) or os.path.getsize(interpret_file) == 0:
            skip_needed = False
            break
            
    if skip_needed and not force:
        result_paths = []
        for file_path in extracted_files:
            phase_name = os.path.basename(file_path).replace("extracted-", "").replace(".md", "")
            interpret_file = os.path.join(journey_map_dir, f"interpret-{phase_name}.md")
            result_paths.append(interpret_file)
        return {
            "status": "success",
            "message": "All interpreted phase files already exist. Skipping AI processing.",
            "result_paths": result_paths
        }

    config = LocalAgentConfig(
        system_instructions="""You are an expert UX researcher. Your task is to analyze raw customer interview data and map it into a strictly formatted Markdown table for a Customer Journey Map.

Follow these strict definitions when interpreting each section:
1. Stage goal: What the customer genuinely wants to achieve during this specific stage (from their perspective). Look for phrases indicating desires or reasons (e.g. "I wanted to...", "I needed..."). Write concisely, starting with an action verb (e.g., "Search for...", "Complete the transaction...").
2. Stage touchpoints: Points of interaction (devices, channels, people, documents). List as specific nouns in a bulleted list using HTML `<br>` tags as separators (e.g., `- Website (mobile)<br>- Customer support`).
3. Stage actions: Concrete physical steps taken, listed in chronological order as a bulleted list using HTML `<br>` tags (e.g., `- Enter search term<br>- Compare prices`).
4. Stage pain points: Obstacles, frustrations, anxieties, or barriers. Clearly describe the problem and its root cause. List as a bulleted list using HTML `<br>` tags (e.g., `- Price info is inconsistent with store staff<br>- Support response time is too slow`).
5. Stage emotion (1-5): Evaluate user satisfaction/frustration based strictly on the following Emotion Scale Table:
   - 1 - Very Negative 😡 (Use when users experience blocked workflows, poor service, feel cheated, or Crying Face 😭 when feeling completely helpless, overwhelmed, or suffer severe data/financial loss)
   - 2 - Slightly Negative 🙁 (Use when users encounter minor UI friction, slow load times, or mild disappointment, or Raised Eyebrow 🤨 when expressing confusion, skepticism, or doubt)
   - 3 - Neutral 😐 (Use when users complete routine, expected tasks without strong positive/negative feelings, or Expressionless Face 😑 when performing tedious but necessary steps)
   - 4 - Positive 🙂 (Use when users experience a smooth, frictionless, and intuitive process, or Smiling Eyes 😊 when feeling reassured, confident, or pleased)
   - 5 - Very Positive 😁 (Use when users achieve goals easily and feel highly satisfied, or Star-Struck 🤩 when experiencing an unexpected "wow" moment, delight, or premium feature)
   Represent strictly in the format: "[Score 1-5] - [Emotion Level] [Primary/Alternative Emoji]" (e.g., "2 - Slightly Negative 🙁", "5 - Very Positive 😁").
6. Stage opportunities & metrics:
   - Opportunities: design/operational solutions addressing the pain points (e.g., `- Build comparison tool<br>- Set up chatbot`).
   - Metrics: quantitative industry-standard metrics to measure effectiveness (e.g., `Bounce rate`, `Conversion rate`, `CSAT`).
   - Combine both into a single bulleted list separated by HTML `<br>` tags.

Additional Rules:
- Maintain Objectivity: Stick closely to what customers actually said and did during the interviews. Do not insert subjective opinions of the product team.
- Use Direct Quotes: Where appropriate, insert a few short, direct quotes from customers inside the cells to help stakeholders empathize.
- ONLY output the Markdown table enclosed in a ```markdown codeblock, without any other conversational text or thinking.
""",
        capabilities=CapabilitiesConfig()
    )

    async def process_file(file_path):
        phase_name = os.path.basename(file_path).replace("extracted-", "").replace(".md", "")
        
        with open(file_path, "r", encoding="utf-8") as f:
            raw_data = f.read()
            
        prompt = f"""
Please analyze the following extracted data for the phase: {phase_name}

--- Extracted Data ---
{raw_data}
----------------------

Output a Markdown table strictly following this format. Ensure that touchpoints, actions, pain points, and opportunities & metrics are formatted as bullet points using `<br>` as the separator:

```markdown
# Interpret - {phase_name}

| Category | Details |
| :--- | :--- |
| **Stage goal** | [Concise goal starting with action verb] |
| **Stage touchpoints** | - [Touchpoint 1]<br>- [Touchpoint 2] |
| **Stage actions** | - [Chronological action 1]<br>- [Chronological action 2] |
| **Stage pain points** | - [Pain point 1: description and root cause]<br>- [Pain point 2] |
| **Stage emotion (1-5)** | [Score 1-5] - [Emotion Level] [Emoji] (e.g., 2 - Slightly Negative 🙁) |
| **Stage opportunities & metrics** | - Opportunities: [Opportunity description]<br>- Metrics: [KPI/Metric description] |
```
"""
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(1, max_retries + 1):
            try:
                async with Agent(config) as agent:
                    response = await agent.chat(prompt)
                    
                    full_text = ""
                    async for token in response:
                        full_text += token
                        
                    match = re.search(r'```(?:markdown)?\n?(.*?)\n?```', full_text, re.DOTALL)
                    if match:
                        updated_content = match.group(1).strip()
                    else:
                        updated_content = full_text.strip()
                    
                    if not updated_content:
                        raise ValueError("AI returned empty content")
                        
                    # Validate the output table structure
                    is_valid, err_msg = validate_table(updated_content)
                    if not is_valid:
                        raise ValueError(f"Table validation failed: {err_msg}")
                        
                    return {"status": "success", "phase": phase_name, "content": updated_content}
            except Exception as e:
                if attempt == max_retries:
                    return {"status": "error", "phase": phase_name, "message": f"AI processing error on interpret-phases ({phase_name}) after {max_retries} retries: {e}"}
                print(f"Attempt {attempt} failed for {phase_name}, retrying in {retry_delay}s... Error: {e}", file=sys.stderr)
                await asyncio.sleep(retry_delay)
                retry_delay *= 2

    # Run AI calls concurrently
    tasks = [process_file(f) for f in extracted_files]
    results = await asyncio.gather(*tasks)
    
    errors = []
    success_contents = {}
    for r in results:
        if isinstance(r, dict):
            if r["status"] == "error":
                errors.append(f"Phase '{r['phase']}': {r['message']}")
            else:
                success_contents[r["phase"]] = r["content"]
        else:
            errors.append(f"Unexpected error: {r}")
            
    if errors:
        # Atomic behavior: do not write any files if any phase failed
        return {
            "status": "error",
            "message": "AI processing failed on one or more phases:\n" + "\n".join(errors)
        }

    # Write files atomically (only if all succeeded)
    result_paths = []
    for file_path in extracted_files:
        phase_name = os.path.basename(file_path).replace("extracted-", "").replace(".md", "")
        interpret_file = os.path.join(journey_map_dir, f"interpret-{phase_name}.md")
        content = success_contents[phase_name]
        with open(interpret_file, "w", encoding="utf-8") as f:
            f.write(content)
        result_paths.append(interpret_file)

    return {"status": "success", "message": f"Successfully interpreted {len(result_paths)} phases.", "result_paths": result_paths}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Interpret Phase Skill Script")
    parser.add_argument("--folder", type=str, required=True, help="Path to Journey Map folder")
    parser.add_argument("--force", action="store_true", help="Force AI processing even if output files exist")
    args = parser.parse_args()
    
    result = asyncio.run(interpret_phases(args.folder, force=args.force))
    print(json.dumps(result))
