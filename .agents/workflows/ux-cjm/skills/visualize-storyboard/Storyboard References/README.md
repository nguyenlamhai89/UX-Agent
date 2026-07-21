# Storyboard References

Place your reference images (`.png`, `.jpg`, `.jpeg`, `.webp`) in this folder.

## Purpose

These images serve as **visual style references** for the AI image generation model (Nano Banana Pro). When generating each comic panel, the script will:

1. Load **all images** from this folder
2. Upload them to the Gemini API via the Files API
3. Pass them alongside the art style guide and panel script as multimodal input
4. The AI model uses these references to match the exact illustration style

## Guidelines

- **More references = stronger style consistency** across all 5 panels
- Use images that clearly demonstrate the desired art style (line art quality, color palette, character design, composition)
- Supported formats: PNG, JPG, JPEG, WEBP
- The folder can contain any number of reference images (recommended: 2-5 for optimal results)
- If this folder is empty, generation will proceed without style references (with a warning)
