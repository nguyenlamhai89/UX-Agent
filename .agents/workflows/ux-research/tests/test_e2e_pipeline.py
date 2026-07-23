import asyncio
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


ROOT = Path(__file__).parents[4]
INTERVIEW = ROOT / ".agents" / "workflows" / "ux-interview"
MAP_JOURNEY = ROOT / ".agents" / "workflows" / "ux-map-journey"
VISUALIZE = ROOT / ".agents" / "workflows" / "ux-research" / "skills" / "visualize-insights"
SEND_EMAIL = ROOT / ".agents" / "workflows" / "ux-research" / "skills" / "send-email"
sys.path[:0] = [
    str(INTERVIEW / "skills" / "create-questionnaire-table" / "scripts"),
    str(INTERVIEW / "skills" / "map-transcript" / "scripts"),
    str(INTERVIEW / "skills" / "saturate-insights" / "scripts"),
    str(MAP_JOURNEY / "skills" / "extract-phases" / "scripts"),
    str(MAP_JOURNEY / "skills" / "interpret-phases" / "scripts"),
    str(MAP_JOURNEY / "skills" / "extract-map" / "scripts"),
    str(VISUALIZE / "scripts"),
    str(SEND_EMAIL / "scripts"),
]

mock_antigravity = MagicMock()
mock_antigravity.Agent = MagicMock()
mock_antigravity.LocalAgentConfig = MagicMock()
mock_antigravity.CapabilitiesConfig = MagicMock()
sys.modules["google.antigravity"] = mock_antigravity

from extract_all_phases import extract_all_phases  # noqa: E402
from extract_map import extract_map  # noqa: E402
from insights_pipeline import (  # noqa: E402
    finalize_pipeline as finalize_insights,
    next_batch as next_insight_batch,
    next_consolidation_batch,
    prepare_consolidation,
    prepare_final_consolidation,
    prepare_pipeline as prepare_insights,
    record_consolidation_success,
    record_success as record_insight_success,
)
from mapping_pipeline import (  # noqa: E402
    finalize_pipeline as finalize_mapping,
    next_batch as next_mapping_batch,
    prepare_pipeline as prepare_mapping,
    record_success as record_mapping_success,
)
from run_interpret import interpret_phases  # noqa: E402
from send_email import prepare_email_draft, send_approved_email  # noqa: E402
from validate_questionnaire import validate_questionnaire  # noqa: E402
from visualize_insights import generate_report  # noqa: E402


PHASES = ["Awareness", "Consideration", "Decision Making", "Usage", "Advocacy"]


class MockAgentContext:
    def __init__(self, *args, **kwargs):
        self.agent = AsyncMock()

        async def response_stream():
            yield """```markdown
# Interpret - Phase
| Category | Details |
| :--- | :--- |
| **Stage goal** | Complete the stage |
| **Stage touchpoints** | App |
| **Stage actions** | Complete task |
| **Stage pain points** | Minor friction |
| **Stage emotion (1-5)** | 3 - Neutral 😐 |
| **Stage opportunities & metrics** | Improve completion rate |
```"""

        self.agent.chat.return_value = response_stream()

    async def __aenter__(self):
        return self.agent

    async def __aexit__(self, exc_type, exc, traceback):
        return False


def _questionnaire():
    rows = [
        f"| {index} | {phase} | Question {index}? | Variable {index} |"
        for index, phase in enumerate(PHASES, start=1)
    ]
    return "\n".join(
        [
            "# Questionnaire",
            "",
            "| # | Theme | Question | Observed Variable |",
            "|---|---|---|---|",
            *rows,
        ]
    )


def _transcript(alias):
    lines = ["# Transcript", ""]
    for index, phase in enumerate(PHASES, start=1):
        lines.extend(
            [
                f"[00:{index * 2:02d}] Interviewer: Question {index}?",
                f"[00:{index * 2 + 1:02d}] {alias}: {phase} works for {alias}.",
            ]
        )
    return "\n".join(lines) + "\n"


def _mapped_candidate(alias):
    rows = []
    for index, phase in enumerate(PHASES, start=1):
        quote = f"{phase} works for {alias}."
        response = (
            f'[00:{index * 2 + 1:02d}] **<mark style="background-color: yellow;">'
            f"{quote}</mark>**"
        )
        rows.append(
            f"| {index} | {phase} | Question {index}? | Variable {index} | {response} |"
        )
    return "\n".join(
        [
            "# Mapped Transcript",
            "",
            f"| # | Theme | Question | Observed Variable | {alias} |",
            "|---|---|---|---|---|",
            *rows,
            "",
            "> **Mapping Summary**: Total rows: 5 | Answered: 5 | N/A: 0 | Transcript coverage: [00:02] to [00:11]",
        ]
    )


def _run_transcribe_pipeline(project, interview):
    questionnaire = interview / "full-questionnaire.md"
    questionnaire.write_text(_questionnaire(), encoding="utf-8")
    assert validate_questionnaire(str(questionnaire))["status"] == "success"
    for alias in ("user1", "user2"):
        (interview / f"transcript_{alias}.md").write_text(
            _transcript(alias), encoding="utf-8"
        )

    assert prepare_mapping(str(project), max_workers=4)["counts"] == {"pending": 2}
    mapping_batch = next_mapping_batch(str(project), now=10_000)
    for task in mapping_batch["tasks"]:
        Path(task["candidate_file"]).write_text(
            _mapped_candidate(task["audio_name"]), encoding="utf-8"
        )
        assert record_mapping_success(str(project), task["audio_name"])["status"] == "validated"
    mapped_result = finalize_mapping(str(project))
    assert mapped_result["status"] == "success"
    mapped_file = Path(mapped_result["combined_file"])

    assert prepare_insights(str(mapped_file), max_workers=4)["counts"] == {"pending": 2}
    insight_batch = next_insight_batch(str(mapped_file), now=10_000)
    for task in insight_batch["tasks"]:
        participant = task["participant"]
        candidate = {
            "participant": participant,
            "insights": [
                {
                    "local_id": f"{participant}-001",
                    "theme": "Awareness",
                    "insight": "Awareness works reliably, because the stage is clear",
                    "evidence": [
                        {
                            "question_number": "1",
                            "theme": "Awareness",
                            "question": "Question 1?",
                            "observed_variable": "Variable 1",
                            "timestamp": "00:03",
                            "quote": f"Awareness works for {participant}.",
                        }
                    ],
                }
            ],
        }
        Path(task["candidate_file"]).write_text(
            json.dumps(candidate), encoding="utf-8"
        )
        recorded = record_insight_success(str(mapped_file), participant)
        assert recorded["status"] == "validated", recorded

    assert prepare_consolidation(str(mapped_file))["batch_count"] == 1
    consolidation_task = next_consolidation_batch(str(mapped_file), now=10_000)["tasks"][0]
    consolidation_input = json.loads(
        Path(consolidation_task["input_file"]).read_text(encoding="utf-8")
    )
    master_candidate = {
        "master_insights": [
            {
                "theme": "Awareness",
                "insight": "Awareness works reliably, because the stage is clear",
                "evidence_ids": [
                    evidence_id
                    for insight in consolidation_input["local_insights"]
                    for evidence_id in insight["evidence_ids"]
                ],
            }
        ]
    }
    Path(consolidation_task["candidate_file"]).write_text(
        json.dumps(master_candidate), encoding="utf-8"
    )
    assert record_consolidation_success(
        str(mapped_file), consolidation_task["batch_id"]
    )["status"] == "validated"
    assert prepare_final_consolidation(str(mapped_file))["status"] == "validated"
    insights_result = finalize_insights(str(mapped_file))
    assert insights_result["status"] == "success"
    return mapped_file, interview / "insights.md"


def test_e2e_pipeline_runs_through_approved_mock_email_send(tmp_path):
    project = tmp_path / "research-project"
    interview = project / "Interview"
    interview.mkdir(parents=True)
    mapped_file, insights_file = _run_transcribe_pipeline(project, interview)

    assert extract_all_phases(str(interview)) is True
    with patch("run_interpret.Agent", new=MockAgentContext):
        interpreted = asyncio.run(interpret_phases(str(interview)))
    assert interpreted["status"] == "success"
    journey_result = asyncio.run(extract_map(str(interview)))
    assert journey_result["status"] == "success"
    journey_file = interview / "Journey Map" / "journey-map.md"

    report = asyncio.run(
        generate_report(
            {
                "insights_path": str(insights_file),
                "transcript_path": str(mapped_file),
                "full_transcript_paths": [
                    str(interview / "transcript_user1.md"),
                    str(interview / "transcript_user2.md"),
                ],
                "journey_path": str(journey_file),
                "media_paths": [],
                "output_dir": str(interview / "Research Report"),
                "project_name": "Complete UX Research",
                "open_browser": False,
            }
        )
    )
    assert report["status"] == "success"
    output_file = Path(report["output_file"])
    manifest_file = Path(report["manifest_file"])
    assert output_file.is_file()
    assert manifest_file.is_file()
    output = output_file.read_text(encoding="utf-8")
    assert "Awareness works reliably, because the stage is clear" in output
    assert "Journey Map" in output
    assert "Stage Emotion (1-5)" in output

    skipped = asyncio.run(
        generate_report(
            {
                "insights_path": str(insights_file),
                "transcript_path": str(mapped_file),
                "full_transcript_paths": [
                    str(interview / "transcript_user1.md"),
                    str(interview / "transcript_user2.md"),
                ],
                "journey_path": str(journey_file),
                "media_paths": [],
                "output_dir": str(interview / "Research Report"),
                "project_name": "Complete UX Research",
                "open_browser": False,
            }
        )
    )
    assert skipped["status"] == "skipped"
    assert skipped["input_signature"] == report["input_signature"]

    draft = prepare_email_draft(
        skipped,
        folder_path=str(project),
        bcc_recipients=["stakeholder@example.com"],
    )
    assert draft["status"] == "awaiting_approval"
    assert draft["draft"]["from"] == "nguyenlamhai89@gmail.com"
    assert draft["draft"]["to"] == []
    assert draft["draft"]["cc"] == []
    assert draft["draft"]["attachment_path"] == skipped["output_file"]
    assert "Hướng dẫn mở báo cáo" in draft["draft"]["body"]

    mocked_send = subprocess.CompletedProcess([], 0, stdout="SENT\n", stderr="")
    with patch("send_email.subprocess.run", return_value=mocked_send) as run:
        cancelled = send_approved_email(draft, approval_token=None)
        assert cancelled["status"] == "cancelled"
        assert cancelled["error"]["code"] == "NOT_APPROVED"
        run.assert_not_called()

        email_result = send_approved_email(
            draft,
            approval_token=draft["approval_token"],
        )

    assert email_result == {
        "status": "success",
        "sent": True,
        "sender": "nguyenlamhai89@gmail.com",
        "recipient_count": 1,
        "attachment_path": skipped["output_file"],
    }
    run.assert_called_once()
