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
        base_dir / "skills" / "saturate-insights" / "scripts" / "insights_pipeline.py"
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

    mapped_file = interview_dir / "mapped-transcript.md"
    prepared_insights = _run(saturation_script, "prepare", mapped_file)
    assert prepared_insights["input_file"] == str(mapped_file)
    extraction_batch = _run(saturation_script, "next-batch", mapped_file)
    assert len(extraction_batch["tasks"]) == 2
    extraction_definitions = {
        "User 1": {
            "timestamp": "00:30",
            "quote": "Khá tốt",
            "insight": "Hài lòng với ứng dụng, do trải nghiệm khá tốt",
        },
        "user2": {
            "timestamp": "00:20",
            "quote": "Nút bấm hơi khó nhìn",
            "insight": "Khó quan sát nút bấm, do nút bấm hơi khó nhìn",
        },
    }
    for task in extraction_batch["tasks"]:
        definition = extraction_definitions[task["participant"]]
        candidate = {
            "participant": task["participant"],
            "insights": [
                {
                    "local_id": f"{task['participant']}-001",
                    "theme": "Trải nghiệm",
                    "insight": definition["insight"],
                    "evidence": [
                        {
                            "question_number": "2",
                            "theme": "Trải nghiệm",
                            "question": "Bạn nghĩ sao về ứng dụng",
                            "observed_variable": "Tính năng dễ dùng",
                            "timestamp": definition["timestamp"],
                            "quote": definition["quote"],
                        }
                    ],
                }
            ],
        }
        Path(task["candidate_file"]).write_text(
            json.dumps(candidate, ensure_ascii=False), encoding="utf-8"
        )
        recorded = _run(
            saturation_script,
            "record-success",
            mapped_file,
            task["participant"],
        )
        assert recorded["status"] == "validated"

    prepared_consolidation = _run(
        saturation_script, "prepare-consolidation", mapped_file
    )
    assert prepared_consolidation["batch_count"] == 1
    consolidation_batch = _run(
        saturation_script, "next-consolidation-batch", mapped_file
    )
    task = consolidation_batch["tasks"][0]
    consolidation_input = json.loads(
        Path(task["input_file"]).read_text(encoding="utf-8")
    )
    master_candidate = {
        "master_insights": [
            {
                "theme": insight["theme"],
                "insight": insight["insight"],
                "evidence_ids": insight["evidence_ids"],
            }
            for insight in consolidation_input["local_insights"]
        ]
    }
    Path(task["candidate_file"]).write_text(
        json.dumps(master_candidate, ensure_ascii=False), encoding="utf-8"
    )
    assert _run(
        saturation_script,
        "record-consolidation-success",
        mapped_file,
        task["batch_id"],
    )["status"] == "validated"
    assert _run(
        saturation_script, "prepare-final-consolidation", mapped_file
    )["status"] == "validated"
    saturation = _run(saturation_script, "finalize", mapped_file)
    assert saturation["status"] == "success"
    assert (interview_dir / "insights.md").exists()
    assert (interview_dir / "all-insights-User_1.md").exists()
    assert (interview_dir / "all-insights-user2.md").exists()
    assert (interview_dir / "insights-data.json").exists()
    assert (interview_dir / "insights-review-manifest.md").exists()
    assert (interview_dir / "saturation-chart.png").exists()
    assert not (interview_dir / "temp_insights.json").exists()
