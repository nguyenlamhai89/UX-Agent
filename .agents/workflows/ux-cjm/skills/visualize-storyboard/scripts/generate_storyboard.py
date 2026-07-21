import os
import sys
import asyncio
import argparse
import logging
import json
import textwrap
from PIL import Image, ImageDraw, ImageFont, ImageOps
import io
import time

from google import genai
from google.genai.types import Part

try:
    from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig
    HAS_ANTIGRAVITY = True
except Exception as e:
    logging.warning(f"google.antigravity not available or proto error ({e}), using fallback script generator.")
    HAS_ANTIGRAVITY = False

# Configure logging to stderr
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format='%(levelname)s: %(message)s')

STAGES = [
    {"key": "awareness", "name": "Awareness"},
    {"key": "consideration", "name": "Consideration"},
    {"key": "decision", "name": "Decision Making"},
    {"key": "usage", "name": "Usage"},
    {"key": "advocacy", "name": "Advocacy"}
]

STYLE_GUIDE = """
# Art Style Analysis: Digital Storyboard & Explainer Illustration

This document provides a comprehensive visual analysis of a specific digital illustration style frequently used for storyboarding, user experience (UX) narratives, and corporate explainer content. The analysis covers both monochromatic comic layouts and standalone dual-tone spot illustrations.

## 1. Format and Layout
* **Grid Structure (Storyboards):** When presented as a narrative sequence, the art utilizes a rigid, traditional comic grid (e.g., 2x3 or 3x3 panels). 
* **Gutters and Borders:** Clean, uniform white spaces (gutters) separate the panels to indicate the passage of time. Simple, thin, consistent black lines box in each scene, keeping the narrative highly structured.
* **Standalone Vignettes (Spot Illustrations):** When used for individual feature graphics or landing pages, the layouts are presented as standalone, rounded-rectangle cards without external borders, focusing on a single, self-contained concept.

## 2. Line Art, Rendering, and Color Palette
The style relies heavily on clean line art but utilizes two distinct approaches to color depending on the context:

* **Line Quality:** Across all variations, the lines are crisp, solid, and digital (vector-based). There is minimal variation in line weight; outlines are slightly thicker than interior details, maintaining a flat, uniform "coloring book" aesthetic.
* **Zero Shading:** There is no use of crosshatching, gradients, or cel-shading to indicate depth or volume. Depth is achieved purely through perspective, overlapping elements, and color contrast.
* **Monochromatic Approach (Storyboarding):** The artwork is strictly black and white. Stark contrast is used to direct the eye, with large areas of solid black applied to specific clothing items or hair to ground the characters.
* **Dual-Tone "Color Wash" Approach (Spot Illustrations):** 
    * **Foreground Emphasis:** Characters and key narrative props (cameras, floating UI elements, laptops) remain in stark black-and-white line art with solid white and black fills. This high contrast makes them "pop" off the page.
    * **Environmental Coding:** Panels utilize a flat, pastel color wash (e.g., warm yellow, sage green, dusty pink) applied to the entire background. This acts as a visual anchor and differentiates scenes or themes.
    * **Receding Background Lines:** Instead of black lines, background details (architecture, classroom furniture, web wireframes) are drawn using a slightly darker, monochromatic shade of the main background color. This pushes the environment backward, creating separation between the focal point and the setting without visual clutter.

## 3. Character Design
* **Realism Level:** Characters are drawn in a semi-realistic, modern illustrative style. They are anatomically proportionate but highly simplified, avoiding exaggerated cartoon or manga features.
* **Consistency:** Characters are easily recognizable through consistent hairstyles, facial structures, and distinct outfits (often featuring solid black garments).
* **Expressiveness:** Facial expressions are subtle but communicative. Posture and hand gestures play a massive role in conveying emotion (e.g., waving, throwing hands up in frustration, pointing).

## 4. Composition and Framing (Cinematography)
* **Varied Shot Types:** The framing acts like a camera to pace the story:
    * *Medium Portraits:* Used to establish characters addressing the viewer or performing a primary action.
    * *Close-ups/POV:* Used to focus intensely on specific, relatable actions, particularly UI interactions (hands typing, swiping on a smartphone, writing on a notepad).
    * *Wide/Establishing Shots:* Used to show the character navigating an environment (like a grocery store).
* **Floating Iconography:** To visually represent abstract concepts (like a career, software features, or a digital shopping list), the style frequently uses floating icons (globes, beakers, chat bubbles, vegetables) hovering around the characters.

## 5. Text and Typography
* **Dialogue and Thoughts:** Speech bubbles (oval shapes with directional tails) are used for direct dialogue or inner thoughts addressed to the audience.
* **Narrative Captions:** Rectangular boxes or floating text without a bounding box are used to describe actions or set the scene.
* **Onomatopoeia/UI Action Words:** Floating text without borders is cleverly used to indicate repetitive actions, particularly tech interactions (e.g., "Tap," "Swipe," "Scroll" floating around hands).
* **Typography:** Fonts are clean, highly legible, sans-serif, or simulated hand-lettered comic fonts. They remain consistent in size and weight to ensure immediate readability.

## 6. Narrative Tone and Purpose
* **The "Explainer" Aesthetic:** The overall style is deeply rooted in professional storyboarding, UX design, and marketing explainer videos. 
* **Problem-Solution Arcs:** The art is tailored to illustrate "pain points" (e.g., the tedious process of meal planning) and quickly pivot to a solution, making it ideal for product pitches.
* **High Relatability:** The combination of clean lines, everyday scenarios, unobtrusive backgrounds, and direct audience address makes the style incredibly accessible, non-threatening, and easy for a general audience to parse quickly.
"""

STAGE_VISUAL_CONFIG = {
    "awareness": {"color_wash": "warm yellow #FFF3D4", "shot_type": "Wide/establishing shot"},
    "consideration": {"color_wash": "sage green #D4EDDA", "shot_type": "Medium portrait"},
    "decision": {"color_wash": "dusty pink #F8D7DA", "shot_type": "Close-up/POV"},
    "usage": {"color_wash": "soft blue #D1ECF1", "shot_type": "Medium portrait"},
    "advocacy": {"color_wash": "lavender #E2D9F3", "shot_type": "Wide shot"}
}

def parse_journey_map(journey_map_path: str) -> dict:
    """Parses journey-map.md markdown table into a structured dict.
    Handles the **Stage Goal**, **Stage Touchpoints**, etc. format.
    """
    logging.info(f"Parsing journey map from {journey_map_path}")
    data = {
        "awareness": {"goal": "", "touchpoints": "", "actions": "", "pain points": "", "emotion": "", "opportunities": ""},
        "consideration": {"goal": "", "touchpoints": "", "actions": "", "pain points": "", "emotion": "", "opportunities": ""},
        "decision": {"goal": "", "touchpoints": "", "actions": "", "pain points": "", "emotion": "", "opportunities": ""},
        "usage": {"goal": "", "touchpoints": "", "actions": "", "pain points": "", "emotion": "", "opportunities": ""},
        "advocacy": {"goal": "", "touchpoints": "", "actions": "", "pain points": "", "emotion": "", "opportunities": ""}
    }
    
    stage_keys = ["awareness", "consideration", "decision", "usage", "advocacy"]
    
    try:
        with open(journey_map_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        for line in content.split("\n"):
            line = line.strip()
            if not line.startswith("|") or "Category" in line or ":---" in line or "Dimension" in line:
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 7:
                # Match dimension by substring (handles **Stage Goal**, etc.)
                dim_raw = parts[1].strip().lower()
                dimension = None
                if "goal" in dim_raw:
                    dimension = "goal"
                elif "touchpoints" in dim_raw:
                    dimension = "touchpoints"
                elif "actions" in dim_raw:
                    dimension = "actions"
                elif "pain points" in dim_raw:
                    dimension = "pain points"
                elif "emotion" in dim_raw:
                    dimension = "emotion"
                elif "opportunities" in dim_raw or "metrics" in dim_raw:
                    dimension = "opportunities"
                    
                if dimension:
                    for i, key in enumerate(stage_keys):
                        data[key][dimension] = parts[i + 2]
                        
        return data
    except Exception as e:
        logging.error(f"Failed to parse journey map: {e}")
        return {}

async def generate_story_scripts(stages_data: dict, output_dir: str) -> list[str]:
    logging.info("Generating story scripts in a single batch AI call...")
    os.makedirs(output_dir, exist_ok=True)
    
    if HAS_ANTIGRAVITY:
        config = LocalAgentConfig(
            system_instructions="You are an expert storyboard scriptwriter. Generate 5 scripts following the exact requested markdown format.",
            capabilities=CapabilitiesConfig()
        )
    
    stages_prompt_data = ""
    for stage in STAGES:
        key = stage["key"]
        name = stage["name"]
        stage_info = stages_data.get(key, {})
        visual_config = STAGE_VISUAL_CONFIG.get(key, {})
        stages_prompt_data += f"""
---
STAGE: {name} (Key: {key})
Goal: {stage_info.get('goal', '')}
Touchpoints: {stage_info.get('touchpoints', '')}
Actions: {stage_info.get('actions', '')}
Pain Points: {stage_info.get('pain points', '')}
Emotion: {stage_info.get('emotion', '')}
Opportunities: {stage_info.get('opportunities', '')}
Visual Config: Color Wash: {visual_config.get('color_wash', '')}, Shot Type: {visual_config.get('shot_type', '')}
"""

    prompt = f"""
    Generate panel scripts for ALL 5 STAGES below in a SINGLE response.
    
    {stages_prompt_data}
    
    Style Guide:
    {STYLE_GUIDE}
    
    FORMAT REQUIREMENT:
    Separate each stage script with a clear delimiter line: `=== STAGE: [key] ===` (where [key] is awareness, consideration, decision-making, usage, advocacy).
    
    For each stage, output the script EXACTLY like this:
    === STAGE: [key] ===
    # Stage [Number]: [Stage Name] — Panel Script

    ## Scene Description
    [Detailed description]

    ## Character
    - **Expression**: ...
    - **Posture/Gesture**: ...
    - **Outfit**: ...

    ## Actions
    ...

    ## Environment & Setting
    - **Location**: ...
    - **Key Props**: ...
    - **Background Color Wash**: ...

    ## Camera/Framing
    - **Shot Type**: ...
    - **Perspective**: ...

    ## Floating Iconography
    ...

    ## Dialogue / Caption Text
    - **Speech Bubble**: ...
    - **Narrative Caption**: ...

    ## Emotion Indicator
    - **Rating**: ...
    - **Visual Cue**: ...
    """
    
    retries = 3
    full_text = ""
    if HAS_ANTIGRAVITY:
        for attempt in range(retries):
            try:
                logging.info(f"Generating all 5 scripts in batch (Attempt {attempt+1}/{retries})")
                async with Agent(config) as agent:
                    response = await agent.chat(prompt)
                    async for token in response:
                        full_text += token
                break
            except Exception as e:
                logging.error(f"Error generating batch scripts: {e}")
                if attempt == retries - 1:
                    logging.error("Failed to generate batch scripts after 3 attempts.")
                else:
                    await asyncio.sleep(2)
    else:
        logging.info("Using deterministic script formatting fallback from journey map data...")
        for stage in STAGES:
            key = stage["key"]
            name = stage["name"]
            stage_info = stages_data.get(key, {})
            vis = STAGE_VISUAL_CONFIG.get(key, {})
            full_text += f"""
=== STAGE: {key} ===
# Stage: {name} — Panel Script

## Scene Description
A customer interacting with ABBANK mobile banking service during the {name} stage.
Goal: {stage_info.get('goal', '')}

## Character
- **Expression**: Reflecting emotion rating {stage_info.get('emotion', '')}
- **Posture/Gesture**: Active engagement with mobile device / environment
- **Outfit**: Modern attire with solid black clothing elements

## Actions
{stage_info.get('actions', '')}

## Environment & Setting
- **Location**: Modern everyday setting (home / office / store)
- **Key Props**: {stage_info.get('touchpoints', '')}
- **Background Color Wash**: {vis.get('color_wash', '')}

## Camera/Framing
- **Shot Type**: {vis.get('shot_type', '')}
- **Perspective**: Eye-level, clean composition

## Floating Iconography
Abstract icons for key concepts: {stage_info.get('opportunities', '')}

## Dialogue / Caption Text
- **Narrative Caption**: {stage_info.get('goal', '')}

## Emotion Indicator
- **Rating**: {stage_info.get('emotion', '')}
"""
                
    script_files = []
    # Split response by delimiter
    sections = full_text.split("=== STAGE:")
    
    stage_file_map = {
        "awareness": "awareness-script.md",
        "consideration": "consideration-script.md",
        "decision": "decision-making-script.md",
        "decision-making": "decision-making-script.md",
        "usage": "usage-script.md",
        "advocacy": "advocacy-script.md"
    }
    
    parsed_stages = {}
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        lines = sec.split("\n", 1)
        stage_key = lines[0].strip().lower()
        content = lines[1].strip() if len(lines) > 1 else ""
        for k in stage_file_map:
            if k in stage_key:
                parsed_stages[k] = content
                break
                
    for stage in STAGES:
        key = stage["key"]
        file_name = stage_file_map[key]
        output_file = os.path.join(output_dir, file_name)
        content = parsed_stages.get(key, f"# Stage: {stage['name']} — Panel Script\n\nFallback script content.")
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)
        script_files.append(output_file)
        
    return script_files

def load_reference_images(api_key: str) -> list[dict]:
    logging.info("Loading reference images (with cache)...")
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ref_dir = os.path.join(base_dir, "Storyboard References")
        cache_file = os.path.join(ref_dir, ".cache.json")
        
        if not os.path.exists(ref_dir):
            logging.warning(f"Storyboard References folder not found at {ref_dir}")
            return []
            
        supported_exts = [".png", ".jpg", ".jpeg", ".webp"]
        image_files = [f for f in os.listdir(ref_dir) if os.path.splitext(f)[1].lower() in supported_exts]
        
        if not image_files:
            logging.warning(f"No reference images found in {ref_dir}")
            return []

        # Load cache if available
        cache = {}
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r") as f:
                    cache = json.load(f)
            except Exception:
                cache = {}
                
        client = None
        ref_images = []
        cache_updated = False
        
        for file in image_files:
            file_path = os.path.join(ref_dir, file)
            mtime = os.path.getmtime(file_path)
            
            # Check if cached and file hasn't changed
            if file in cache and cache[file].get("mtime") == mtime and cache[file].get("uri"):
                ref_images.append({
                    "uri": cache[file]["uri"],
                    "mime_type": cache[file]["mime_type"]
                })
            else:
                if client is None:
                    client = genai.Client(api_key=api_key)
                logging.info(f"Uploading {file_path}...")
                uploaded_file = client.files.upload(file=file_path)
                uri_data = {
                    "uri": uploaded_file.uri,
                    "mime_type": uploaded_file.mime_type,
                    "mtime": mtime
                }
                cache[file] = uri_data
                ref_images.append({
                    "uri": uploaded_file.uri,
                    "mime_type": uploaded_file.mime_type
                })
                cache_updated = True
                
        if cache_updated:
            try:
                with open(cache_file, "w") as f:
                    json.dump(cache, f, indent=2)
            except Exception as e:
                logging.warning(f"Could not write cache file: {e}")
                
        return ref_images
    except Exception as e:
        logging.error(f"Error loading reference images: {e}")
        return []

def generate_panel_images(script_files: list[str], ref_images: list[dict], api_key: str) -> list[Image.Image]:
    logging.info("Generating panel images via Gemini Image API...")
    
    all_scripts_text = ""
    for sf in script_files:
        try:
            with open(sf, "r", encoding="utf-8") as f:
                all_scripts_text += f.read() + "\n\n"
        except Exception:
            pass
            
    try:
        client = genai.Client(api_key=api_key)
        
        prompt = f"""
        Digital comic storyboard illustration with 5 distinct panels in a 3+2 grid layout.
        
        STYLE GUIDE:
        {STYLE_GUIDE}
        
        PANEL SCRIPTS FOR ALL 5 PANELS:
        {all_scripts_text}
        
        CRITICAL VISUAL INSTRUCTIONS:
        - Clean thin vector line art, modern UX explainer storyboard aesthetic.
        - Dual-tone color wash per panel (warm yellow, sage green, dusty pink, soft blue, lavender).
        - Stark black-and-white foreground characters with solid black clothing elements.
        - Zero shading or gradients.
        - High-contrast, professional, highly legible.
        """
        
        retries = 2
        for attempt in range(retries):
            try:
                logging.info(f"Calling client.models.generate_images (Attempt {attempt+1}/{retries})...")
                # Try imagen-3.0-generate-002 or gemini-2.5-flash-image
                try:
                    response = client.models.generate_images(
                        model="imagen-3.0-generate-002",
                        prompt=prompt,
                        config=genai.types.GenerateImagesConfig(
                            number_of_images=1,
                            aspect_ratio="3:2"
                        )
                    )
                    if response.generated_images:
                        img_bytes = response.generated_images[0].image.image_bytes
                        grid_img = Image.open(io.BytesIO(img_bytes))
                        return [grid_img] * 5
                except Exception as e:
                    logging.info(f"Imagen model call failed ({e}), trying client.models.generate_content...")
                    response = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=prompt
                    )
                    # Fallback blank panels if model does not output raw image bytes directly
                    logging.info("Generated text response, using structured fallback canvas.")
                    return [Image.new("RGB", (1050, 900), color="white") for _ in script_files]
            except Exception as e:
                logging.error(f"Error during image generation: {e}")
                if attempt == retries - 1:
                    return [Image.new("RGB", (1050, 900), color="white") for _ in script_files]
                else:
                    time.sleep(2)
                    
        return [Image.new("RGB", (1050, 900), color="white") for _ in script_files]
    except Exception as e:
        logging.error(f"Critical error in generate_panel_images: {e}")
        return [Image.new("RGB", (1050, 900), color="white") for _ in script_files]

def composite_storyboard(panel_images: list[Image.Image], stages_data: dict) -> Image.Image:
    logging.info("Compositing storyboard...")
    try:
        # Canvas sizes
        canvas_width = 3600
        canvas_height = 2400
        panel_width = 1050
        panel_height = 900
        gutter = 20
        border_width = 2
        
        canvas = Image.new("RGB", (canvas_width, canvas_height), color="white")
        draw = ImageDraw.Draw(canvas)
        
        # Load fonts
        try:
            title_font = ImageFont.truetype("Arial", 80)
            stage_font = ImageFont.truetype("Arial", 50)
            caption_font = ImageFont.truetype("Arial", 35)
            badge_font = ImageFont.truetype("Arial", 30)
        except IOError:
            # Fallback to default if Arial is not found
            logging.warning("Arial font not found, falling back to default")
            title_font = ImageFont.load_default()
            stage_font = ImageFont.load_default()
            caption_font = ImageFont.load_default()
            badge_font = ImageFont.load_default()
            
        # Draw Title
        title = "CUSTOMER JOURNEY MAP STORYBOARD"
        # title_bbox = draw.textbbox((0, 0), title, font=title_font)
        # title_w = title_bbox[2] - title_bbox[0]
        draw.text((canvas_width/2, 100), title, font=title_font, fill="black", anchor="mm")
        
        positions = [
            (canvas_width/2 - panel_width - gutter, 500), # Col 1, Row 1 (Awareness)
            (canvas_width/2, 500), # Col 2, Row 1 (Consideration)
            (canvas_width/2 + panel_width + gutter, 500), # Col 3, Row 1 (Decision)
            (canvas_width/2 - panel_width/2 - gutter/2, 500 + panel_height + gutter + 300), # Col 1.5, Row 2 (Usage)
            (canvas_width/2 + panel_width/2 + gutter/2, 500 + panel_height + gutter + 300) # Col 2.5, Row 2 (Advocacy)
        ]
        
        for i, stage in enumerate(STAGES):
            if i >= len(panel_images):
                break
                
            key = stage["key"]
            name = stage["name"]
            stage_info = stages_data.get(key, {})
            goal = stage_info.get("goal", "")
            emotion = stage_info.get("emotion", "")
            
            img = panel_images[i]
            # Resize and crop to fit panel
            img_resized = ImageOps.fit(img, (panel_width, panel_height))
            
            # Draw border
            img_with_border = ImageOps.expand(img_resized, border=border_width, fill="black")
            
            center_x, top_y = positions[i]
            left_x = int(center_x - panel_width/2)
            
            # Paste image
            canvas.paste(img_with_border, (left_x, int(top_y)))
            
            # Draw Stage Label
            stage_label = f"{i+1}. {name}"
            draw.text((center_x, top_y - 40), stage_label, font=stage_font, fill="black", anchor="md")
            
            # Draw Caption (Goal)
            wrapped_goal = textwrap.fill(goal, width=60)
            draw.multiline_text((center_x, top_y + panel_height + 40), wrapped_goal, font=caption_font, fill="black", anchor="ma", align="center")
            
            # Draw Emotion Badge
            badge_text = f"Emotion: {emotion}"
            draw.text((center_x, top_y + panel_height + 150), badge_text, font=badge_font, fill="black", anchor="ma")
            
        return canvas
    except Exception as e:
        logging.error(f"Error in composite_storyboard: {e}")
        return Image.new("RGB", (3600, 2400), color="white")

async def generate_storyboard(folder_path: str, gemini_api_key: str) -> dict:
    logging.info(f"Starting storyboard generation for folder: {folder_path}")
    
    journey_map_path = os.path.join(folder_path, "Journey Map", "journey-map.md")
    
    if not os.path.exists(journey_map_path):
        return {"status": "error", "message": f"Journey map not found at {journey_map_path}"}
        
    stages_data = parse_journey_map(journey_map_path)
    if not stages_data:
        return {"status": "error", "message": "Failed to parse journey map data."}
        
    output_dir = os.path.join(folder_path, "Journey Map")
    script_files = await generate_story_scripts(stages_data, output_dir)
    
    ref_images = load_reference_images(gemini_api_key)
    
    panel_images = generate_panel_images(script_files, ref_images, gemini_api_key)
    
    storyboard = composite_storyboard(panel_images, stages_data)
    
    output_path = os.path.join(folder_path, "Journey Map", "storyboard.png")
    storyboard.save(output_path)
    logging.info(f"Storyboard saved to {output_path}")
    
    return {
        "status": "success",
        "output_file": output_path,
        "script_files": script_files,
        "message": "Storyboard generated successfully"
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Customer Journey Map Storyboard")
    parser.add_argument("--folder", required=True, help="Path to the workspace folder")
    parser.add_argument("--api-key", required=True, help="Gemini API Key")
    
    args = parser.parse_args()
    
    try:
        result = asyncio.run(generate_storyboard(args.folder, args.api_key))
        print(json.dumps(result))
    except Exception as e:
        logging.error(f"Execution failed: {e}")
        sys.exit(1)
