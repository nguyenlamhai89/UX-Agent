import json
import shutil
import subprocess
import sys
from pathlib import Path


def _run(*args):
    completed = subprocess.run(
        [sys.executable, *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return (
        json.loads(completed.stdout)
        if completed.stdout.strip().startswith("{")
        else completed
    )


def test_e2e_pipeline_starts_from_source_transcripts(tmp_path):
    mock_dir = Path(__file__).parent / "mock-dataset"
    workspace = tmp_path / "workspace"
    interview_dir = workspace / "Interview"
    interview_dir.mkdir(parents=True)

    for filename in (
        "full-questionnaire.md",
        "transcript_user1.md",
        "transcript_user2.md",
        "temp_insights.json",
    ):
        shutil.copy(mock_dir / filename, interview_dir / filename)

    base_dir = Path(__file__).parent.parent
    validation_script = (
        base_dir
        / "skills"
        / "create-questionnaire-table"
        / "scripts"
        / "validate_questionnaire.py"
    )
    controller_script = (
        base_dir / "skills" / "map-transcript" / "scripts" / "mapping_pipeline.py"
    )
    saturation_script = (
        base_dir / "skills" / "saturate-insights" / "scripts" / "saturate_insights.py"
    )

    questionnaire_check = subprocess.run(
        [
            sys.executable,
            str(validation_script),
            str(interview_dir / "full-questionnaire.md"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert questionnaire_check.returncode == 0

    prepared = _run(controller_script, "prepare", workspace, "--max-workers", "4")
    assert prepared["counts"] == {"pending": 2}
    batch = _run(controller_script, "next-batch", workspace)
    assert len(batch["tasks"]) == 2

    for task in batch["tasks"]:
        source = mock_dir / f"mapped-transcript-{task['audio_name']}.md"
        shutil.copy(source, task["candidate_file"])
        recorded = _run(
            controller_script,
            "record-success",
            workspace,
            task["audio_name"],
        )
        assert recorded["status"] == "validated"

    finalized = _run(controller_script, "finalize", workspace)
    assert finalized["status"] == "success"
    assert (interview_dir / "mapped-transcript.md").exists()
    assert (interview_dir / "mapped-transcript-review-01.md").exists()
    assert (interview_dir / "mapping-review-manifest.md").exists()

    saturation = subprocess.run(
        [sys.executable, str(saturation_script), str(workspace), "--generate-only"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert saturation.returncode == 0, saturation.stdout + saturation.stderr
    assert (interview_dir / "insights.md").exists()
    assert (interview_dir / "all-insights-user1.md").exists()
    assert (interview_dir / "all-insights-user2.md").exists()
