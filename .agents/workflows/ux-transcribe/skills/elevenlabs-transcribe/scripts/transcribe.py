import sys
import os
import json
import glob
import time
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from elevenlabs.client import ElevenLabs

def get_audio_files(folder_path):
    patterns = ['*.mp3', '*.wav', '*.m4a', '*.qta']
    files = []
    interview_dir = os.path.join(folder_path, "Interview")
    for pattern in patterns:
        files.extend(glob.glob(os.path.join(interview_dir, pattern)))
    return files

def format_timestamp(seconds):
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"

def transcribe_audio(file_path, api_key, keyterms=None):
    max_retries = 3
    base_delay = 2
    elevenlabs = ElevenLabs(api_key=api_key)
    
    for attempt in range(max_retries):
        try:
            with open(file_path, 'rb') as audio_file:
                transcription = elevenlabs.speech_to_text.convert(
                    file=audio_file,
                    model_id="scribe_v2",
                    diarize=True,
                    keyterms=keyterms
                )
            
            filename = os.path.basename(file_path)
            base_name, _ = os.path.splitext(filename)
            lines = []
            lines.append(f"# INTERVIEW TRANSCRIPT: {filename}\n")
            
            current_speaker = None
            current_text = ""
            start_time = 0
            
            if hasattr(transcription, "words") and transcription.words:
                for word in transcription.words:
                    speaker = getattr(word, "speaker_id", "speaker_0")
                    if speaker != current_speaker:
                        if current_speaker is not None:
                            lines.append(f"**[{format_timestamp(start_time)}] [{current_speaker}]** <br>\n{current_text.strip()}\n")
                        
                        current_speaker = speaker
                        start_time = word.start
                        current_text = word.text
                    else:
                        current_text += " " + word.text.strip()
                
                if current_speaker is not None:
                    lines.append(f"**[{format_timestamp(start_time)}] [{current_speaker}]** <br>\n{current_text.strip()}\n")
                
                return "\n".join(lines)
            else:
                # Fallback if no words array is available
                lines.append(f"**[00:00] [speaker_0]** <br>\n{transcription.text}\n")
                return "\n".join(lines)
                
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))
            else:
                raise Exception(f"Failed to transcribe {file_path} after {max_retries} attempts: {str(e)}")

def process_file(audio_path, folder_path, api_key, keyterms=None):
    filename = os.path.basename(audio_path)
    base_name, _ = os.path.splitext(filename)
    
    interview_dir = os.path.join(folder_path, "Interview")
    os.makedirs(interview_dir, exist_ok=True)
    
    output_file = os.path.join(interview_dir, f"transcript_{base_name}.md")

    if os.path.exists(output_file):
        return {
            "status": "skipped",
            "audio_file": filename,
            "output_file": output_file
        }

    try:
        transcript_text = transcribe_audio(audio_path, api_key, keyterms)
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(transcript_text)
        
        return {
            "status": "success",
            "audio_file": filename,
            "output_file": output_file
        }
    except Exception as e:
        return {
            "status": "error",
            "audio_file": filename,
            "error": str(e)
        }

def main():
    if len(sys.argv) < 2:
        print(json.dumps({
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "Usage: python3 transcribe.py <folder_path> [--keyterms <term1,term2>]"
        }))
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Transcribe audio files in a folder.")
    parser.add_argument("folder_path", help="Path to the audio folder")
    parser.add_argument("--keyterms", help="Comma-separated list of key terms", default=None)
    
    args, _ = parser.parse_known_args()

    folder_path = args.folder_path
    api_key = os.environ.get("ELEVENLABS_API_KEY")

    if not api_key:
        print(json.dumps({
            "status": "error",
            "error_code": "MISSING_API_KEY",
            "message": "ELEVENLABS_API_KEY environment variable is not set."
        }))
        sys.exit(1)
    keyterms = [k.strip() for k in args.keyterms.split(',') if k.strip()] if args.keyterms else None

    if not os.path.isdir(folder_path):
        print(json.dumps({
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": f"Folder not found: {folder_path}"
        }))
        sys.exit(1)

    audio_files = get_audio_files(folder_path)

    if not audio_files:
        print(json.dumps({
            "status": "error",
            "error_code": "NO_AUDIO_FILES",
            "message": f"No supported audio files (.mp3, .wav, .m4a, .qta) found in {folder_path}."
        }))
        sys.exit(1)

    results = []
    errors = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process_file, path, folder_path, api_key, keyterms): path for path in audio_files}
        
        for future in as_completed(futures):
            res = future.result()
            if res["status"] in ["success", "skipped"]:
                results.append({
                    "audio_file": res["audio_file"],
                    "output_file": res["output_file"]
                })
            else:
                errors.append(res)

    if errors:
        print(json.dumps({
            "status": "error",
            "error_code": "API_ERROR",
            "message": "One or more files failed to transcribe.",
            "errors": errors,
            "successful_transcripts": results
        }))
        sys.exit(1)

    print(json.dumps({
        "status": "success",
        "data": {
            "transcripts": results,
            "total": len(results)
        }
    }))

if __name__ == "__main__":
    main()
