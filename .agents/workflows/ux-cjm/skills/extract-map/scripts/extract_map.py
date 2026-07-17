import os
import glob
import asyncio
import re
import argparse
import sys

# Define standard stages and mapping
STAGES = [
    {"key": "awareness", "name": "Awareness"},
    {"key": "consideration", "name": "Consideration"},
    {"key": "decision", "name": "Decision Making"},
    {"key": "usage", "name": "Usage"},
    {"key": "advocacy", "name": "Advocacy"}
]

def parse_markdown_table_sync(file_path: str):
    """Parses the interpret-<phase>.md markdown table into a dictionary."""
    data = {
        "goal": "",
        "touchpoints": "",
        "actions": "",
        "pain points": "",
        "emotion": "",
        "opportunities": ""
    }
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        for line in content.split("\n"):
            line = line.strip()
            if not line.startswith("|") or "Category" in line or ":---" in line:
                continue
            
            parts = line.split("|")
            if len(parts) >= 3:
                key = parts[1].strip().lower()
                value = parts[2].strip()
                
                if "goal" in key:
                    data["goal"] = value
                elif "touchpoints" in key:
                    data["touchpoints"] = value
                elif "actions" in key:
                    data["actions"] = value
                elif "pain points" in key:
                    data["pain points"] = value
                elif "emotion" in key:
                    data["emotion"] = value
                elif "opportunities" in key or "metrics" in key:
                    data["opportunities"] = value
    except Exception as e:
        print(f"Error parsing {file_path}: {e}", file=sys.stderr)
        
    return data

def read_file_sync(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

def write_file_sync(file_path: str, content: str):
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

def glob_sync(pattern: str):
    return glob.glob(pattern)

def sanitize_cell_value(val: str) -> str:
    """Sanitizes cell values to prevent breaking markdown table format."""
    if not val:
        return ""
    # Escape pipe characters
    val = val.replace("|", "\\|")
    # Replace newlines with HTML <br> tags
    val = val.replace("\n", "<br>")
    return val

async def extract_map(folder_path: str):
    if os.path.basename(folder_path.rstrip(os.sep)) == "Journey Map":
        journey_map_dir = folder_path
    else:
        journey_map_dir = os.path.join(folder_path, "Journey Map")

    if not await asyncio.to_thread(os.path.exists, journey_map_dir):
        return {"status": "error", "message": f"Directory not found: {journey_map_dir}"}
        
    journey_map_file = os.path.join(journey_map_dir, "journey-map.md")
    
    # Find all interpret-*.md files asynchronously
    interpret_files = await asyncio.to_thread(glob_sync, os.path.join(journey_map_dir, "interpret-*.md"))
    
    if not interpret_files:
        return {"status": "error", "message": "No interpret-*.md files found."}

    # Map files to stages
    stage_data = {i: {"name": stage["name"], "data": None} for i, stage in enumerate(STAGES)}
    
    # Initialize empty data structures
    for i in stage_data:
        stage_data[i]["data"] = {
            "goal": "",
            "touchpoints": "",
            "actions": "",
            "pain points": "",
            "emotion": "",
            "opportunities": ""
        }
    
    stages_found = set()
    for file_path in interpret_files:
        base_name = os.path.basename(file_path).lower()
        
        # Determine which stage this file belongs to
        matched_stage_idx = -1
        for i, stage in enumerate(STAGES):
            if stage["key"] in base_name:
                matched_stage_idx = i
                break
                
        if matched_stage_idx != -1:
            stage_data[matched_stage_idx]["data"] = await asyncio.to_thread(parse_markdown_table_sync, file_path)
            stages_found.add(matched_stage_idx)

    # 2. Complete/Warnings Check
    missing_stages = [STAGES[i]["name"] for i in range(len(STAGES)) if i not in stages_found]
    warnings = []
    if missing_stages:
        warnings.append(f"Missing stages: {', '.join(missing_stages)}")
        
    for idx in stages_found:
        empty_fields = [k for k, v in stage_data[idx]["data"].items() if not v]
        if empty_fields:
            warnings.append(f"Stage '{STAGES[idx]['name']}' has empty fields: {', '.join(empty_fields)}")

    # Generate the Markdown table programmatically
    def cell(val):
        return sanitize_cell_value(val)
        
    def pad(row_data):
        return " | ".join(row_data)

    lines = []
    lines.append("# Customer Journey Map")
    lines.append("")
    
    # Header
    headers = ["Dimension"] + [f"Stage {i+1}: {stage_data[i]['name']}" for i in range(5)]
    lines.append("| " + pad(headers) + " |")
    
    # Separator
    lines.append("| " + pad([":---"] * 6) + " |")
    
    # Goal
    goals = ["**Stage Goal**"] + [cell(stage_data[i]["data"]["goal"]) for i in range(5)]
    lines.append("| " + pad(goals) + " |")

    # Touchpoints
    touchpoints = ["**Stage Touchpoints**"] + [cell(stage_data[i]["data"]["touchpoints"]) for i in range(5)]
    lines.append("| " + pad(touchpoints) + " |")

    # Actions
    actions = ["**Stage Actions**"] + [cell(stage_data[i]["data"]["actions"]) for i in range(5)]
    lines.append("| " + pad(actions) + " |")

    # Pain Points
    pain_points = ["**Stage Pain Points**"] + [cell(stage_data[i]["data"]["pain points"]) for i in range(5)]
    lines.append("| " + pad(pain_points) + " |")

    # Emotion
    emotions = ["**Stage Emotion (1-5)**"] + [cell(stage_data[i]["data"]["emotion"]) for i in range(5)]
    lines.append("| " + pad(emotions) + " |")

    # Opportunities
    opps = ["**Stage Opportunities & Metrics**"] + [cell(stage_data[i]["data"]["opportunities"]) for i in range(5)]
    lines.append("| " + pad(opps) + " |")

    final_map = "\n".join(lines) + "\n"
    
    # 3. Idempotency Check by content diff
    if await asyncio.to_thread(os.path.exists, journey_map_file):
        try:
            current_map = await asyncio.to_thread(read_file_sync, journey_map_file)
            if current_map == final_map:
                msg = "journey-map.md is already up to date. Skipping processing."
                if warnings:
                    msg += f" Warnings: {'; '.join(warnings)}"
                return {"status": "success", "message": msg}
        except Exception:
            pass # If read fails, proceed to overwrite
    
    # 4. Write output with try-except wrapping
    try:
        await asyncio.to_thread(write_file_sync, journey_map_file, final_map)
    except (OSError, PermissionError) as e:
        return {"status": "error", "message": f"Failed to write journey-map.md due to filesystem error: {e}"}

    success_msg = "Successfully mapped all interpreted phases into journey-map.md deterministically."
    if warnings:
        success_msg += f" Warnings: {'; '.join(warnings)}"

    return {"status": "success", "message": success_msg}

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract Map Skill Script")
    parser.add_argument("--folder", type=str, required=True, help="Path to project folder")
    args = parser.parse_args()
    
    result = asyncio.run(extract_map(args.folder))
    import json
    print(json.dumps(result))


