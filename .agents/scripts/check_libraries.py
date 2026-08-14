import os
import sys
import json
import urllib.request
from importlib.metadata import version, PackageNotFoundError

# Libraries to check for workflows and skills in this workspace
LIBRARIES = {
    "elevenlabs": "Required for voice synthesis and audio transcription in the ElevenLabs Transcribe skill.",
    "docling": "Required for PDF extraction in the Convert Research Paper to Markdown skill.",
    "matplotlib": "Required for rendering insights charts and matrices in the Saturate Insights skill.",
    "pytest": "Required for running the unit tests of skills and workflows.",
}

def get_installed_version(pkg):
    try:
        return version(pkg)
    except PackageNotFoundError:
        return None

def get_latest_version(pkg):
    url = f"https://pypi.org/pypi/{pkg}/json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Antigravity/VersionCheck"})
        with urllib.request.urlopen(req, timeout=2) as response:
            data = json.loads(response.read().decode())
            return data["info"]["version"]
    except Exception:
        # Offline or connection timeout
        return None

def check_versions():
    target_pkgs = set()
    if len(sys.argv) > 1:
        args = [arg.lower().lstrip("-") for arg in sys.argv[1:]]
        # Map skill aliases if needed
        skill_map = {
            "transcribe-audios": ["elevenlabs"],
            "transcribe": ["elevenlabs"],
            "docling": ["docling"],
            "convert-paper": ["docling"],
            "saturate-insights": ["matplotlib"],
            "insights": ["matplotlib"],
            "tests": ["pytest"],
            "pytest": ["pytest"]
        }
        for arg in args:
            if arg in skill_map:
                target_pkgs.update(skill_map[arg])
            elif arg in LIBRARIES:
                target_pkgs.add(arg)
            else:
                target_pkgs.add(arg)

    check_libraries = {k: v for k, v in LIBRARIES.items() if not target_pkgs or k in target_pkgs}

    print("=" * 60)
    print("      CHECKING DEPENDENCIES AND LIBRARY VERSIONS      ")
    print("=" * 60)
    
    outdated = []
    missing = []
    
    for pkg, description in check_libraries.items():
        installed = get_installed_version(pkg)
        if installed is None:
            print(f"❌ {pkg:<12} | NOT INSTALLED")
            print(f"   ({description})")
            missing.append(pkg)
            continue
            
        latest = get_latest_version(pkg)
        if latest is None:
            print(f"⚠️  {pkg:<12} | Installed: {installed:<8} | Latest: [Could not fetch - Offline]")
        elif installed != latest:
            print(f"🔄 {pkg:<12} | Installed: {installed:<8} | Latest: {latest:<8} [OUTDATED]")
            outdated.append((pkg, installed, latest))
        else:
            print(f"✅ {pkg:<12} | Installed: {installed:<8} | Latest: {latest:<8} [UP-TO-DATE]")
            
    print("=" * 60)
    
    if missing or outdated:
        print("\n💡 Action Recommended to Ensure Workflow Integrity:")
        if missing:
            print("  [Missing Packages] Run the following to install:")
            print(f"    pip install {' '.join(missing)}")
        if outdated:
            print("  [Outdated Packages] Run the following to update:")
            for pkg, _, _ in outdated:
                print(f"    pip install --upgrade {pkg}")
        print()
    else:
        print("\nRequested dependencies are fully installed and up to date!\n")

if __name__ == "__main__":
    check_versions()
