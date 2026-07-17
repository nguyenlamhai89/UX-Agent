import os
import shutil
import subprocess
import pytest
from pathlib import Path
import sys
import json

def test_e2e_pipeline(tmp_path):
    mock_dir = Path(__file__).parent / "mock-dataset"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    interview_dir = workspace / "Interview"
    interview_dir.mkdir()
    
    # 1. Setup mock data
    shutil.copy(mock_dir / "full-questionnaire.md", interview_dir / "full-questionnaire.md")
    shutil.copy(mock_dir / "mapped-transcript-user1.md", interview_dir / "mapped-transcript-user1.md")
    shutil.copy(mock_dir / "mapped-transcript-user2.md", interview_dir / "mapped-transcript-user2.md")
    shutil.copy(mock_dir / "temp_insights.json", interview_dir / "temp_insights.json")
    
    # Paths to scripts
    base_dir = Path(__file__).parent.parent
    val_script = base_dir / "skills" / "create-questionnaire-table" / "scripts" / "validate_questionnaire.py"
    map_script = base_dir / "skills" / "map-transcript" / "scripts" / "map_transcript.py"
    sat_script = base_dir / "skills" / "saturate-insights" / "scripts" / "saturate_insights.py"
    
    python_exec = sys.executable
    
    # Step 1: Validate Questionnaire
    res1 = subprocess.run([python_exec, str(val_script), str(interview_dir / "full-questionnaire.md")], capture_output=True, text=True)
    assert res1.returncode == 0, f"Validation failed: {res1.stderr}\nStdout: {res1.stdout}"
    
    # Step 2: Map Transcript (Merge)
    res2 = subprocess.run([python_exec, str(map_script), str(workspace)], capture_output=True, text=True)
    assert res2.returncode == 0, f"Map transcript failed: {res2.stderr}\nStdout: {res2.stdout}"
    assert (interview_dir / "mapped-transcript.md").exists()
    
    # Step 3: Saturate Insights (Generate JSON -> HTML input)
    res3 = subprocess.run([python_exec, str(sat_script), str(workspace), "--generate-only"], capture_output=True, text=True)
    assert res3.returncode == 0, f"Saturate insights failed: {res3.stderr}\nStdout: {res3.stdout}"
    assert (interview_dir / "insights.md").exists()
    assert (interview_dir / "all-insights-user1.md").exists()
    assert (interview_dir / "all-insights-user2.md").exists()


    

