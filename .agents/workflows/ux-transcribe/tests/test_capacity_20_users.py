import json
import re
import sys
import time
import tracemalloc
from pathlib import Path


MAP_SCRIPTS = Path(__file__).parent.parent / "skills" / "map-transcript" / "scripts"
SATURATION_SCRIPTS = (
    Path(__file__).parent.parent / "skills" / "saturate-insights" / "scripts"
)
sys.path.extend([str(MAP_SCRIPTS), str(SATURATION_SCRIPTS)])

from map_transcript import parse_markdown_table  # noqa: E402
from mapping_pipeline import (  # noqa: E402
    finalize_pipeline as finalize_mapping,
    next_batch as next_mapping_batch,
    prepare_pipeline as prepare_mapping,
    record_success as record_mapping_success,
)
from insights_pipeline import (  # noqa: E402
    finalize_pipeline as finalize_insights,
    next_batch as next_insight_batch,
    next_consolidation_batch,
    next_final_consolidation,
    prepare_consolidation,
    prepare_final_consolidation,
    prepare_pipeline as prepare_insights,
    record_consolidation_success,
    record_final_consolidation_success,
    record_success as record_insight_success,
)


QUESTIONNAIRE = """# Questionnaire

| # | Theme | Question | Observed Variable |
|---|---|---|---|
| 1 | Intro | Who are you? | Identity |
| 2 | Product | What works? | Value |
"""


def _transcript(alias):
    return f"""# Transcript

[00:00] Interviewer: Who are you?
[00:05] {alias}: I am {alias}.
[00:10] Interviewer: What works?
[00:15] {alias}: The workflow works.
"""


def _mapped(alias_or_task):
    alias = alias_or_task["audio_name"] if isinstance(alias_or_task, dict) else alias_or_task
    r1 = f'[00:05] **<mark style="background-color: yellow;">I am {alias}.</mark>**'
    tail = ""
    if alias == "user20":
        tail = "<br><br>" + ("Additional long-form context without a new timestamp. " * 80).strip()
    r2 = f'[00:15] **<mark style="background-color: yellow;">The workflow works.{tail}</mark>**'

    return f"""# Mapped Transcript

| # | Theme | Question | Observed Variable | {alias} |
|---|---|---|---|---|
| 1 | Intro | Who are you? | Identity | {r1} |
| 2 | Product | What works? | Value | {r2} |

> **Mapping Summary**: Total rows: 2 | Answered: 2 | N/A: 0 | Transcript coverage: [00:00] to [00:15]
"""


def test_capacity_twenty_users_with_bounded_batches(tmp_path):
    interview = tmp_path / "Interview"
    interview.mkdir()
    (interview / "full-questionnaire.md").write_text(QUESTIONNAIRE, encoding="utf-8")
    for index in range(1, 21):
        alias = f"user{index:02d}"
        content = _transcript(alias)
        if index == 20:
            content += "\n" + (
                "Additional long-form context without a new timestamp. " * 80
            ).strip()
        (interview / f"transcript_{alias}.md").write_text(
            content,
            encoding="utf-8",
        )

    tracemalloc.start()
    started = time.perf_counter()
    prepared = prepare_mapping(
        str(tmp_path),
        max_workers=4,
        max_tokens=100,
        review_batch_size=5,
    )
    assert prepared["counts"] == {"pending": 20}
    batch_sizes = []
    chunked_tasks = []
    while True:
        batch = next_mapping_batch(str(tmp_path), now=10_000)
        if not batch["tasks"]:
            break
        batch_sizes.append(len(batch["tasks"]))
        chunked_tasks.extend(
            task["audio_name"] for task in batch["tasks"] if task["chunked"]
        )
        for task in batch["tasks"]:
            Path(task["candidate_file"]).write_text(
                _mapped(task),
                encoding="utf-8",
            )
            res = record_mapping_success(str(tmp_path), task["audio_name"])
            assert res["status"] == "validated", f"Failed: {res}"

    assert batch_sizes == [4, 4, 4, 4, 4]
    result = finalize_mapping(str(tmp_path))
    mapped_file = Path(result["combined_file"])

    prepared_insights = prepare_insights(
        str(mapped_file),
        max_workers=4,
        max_insights_per_batch=5,
    )
    assert prepared_insights["counts"] == {"pending": 20}
    extraction_batch_sizes = []
    while True:
        batch = next_insight_batch(str(mapped_file), now=10_000)
        if not batch["tasks"]:
            break
        extraction_batch_sizes.append(len(batch["tasks"]))
        for task in batch["tasks"]:
            participant = task["participant"]
            candidate = {
                "participant": participant,
                "insights": [
                    {
                        "local_id": f"{participant}-001",
                        "theme": "Product value",
                        "insight": "Satisfied with the workflow, because it works reliably",
                        "evidence": [
                            {
                                "question_number": "2",
                                "theme": "Product",
                                "question": "What works?",
                                "observed_variable": "Value",
                                "timestamp": "00:15",
                                "quote": "The workflow works",
                            }
                        ],
                    }
                ],
            }
            Path(task["candidate_file"]).write_text(
                json.dumps(candidate), encoding="utf-8"
            )
            assert (
                record_insight_success(str(mapped_file), participant)["status"]
                == "validated"
            )
    assert extraction_batch_sizes == [4, 4, 4, 4, 4]

    consolidation = prepare_consolidation(str(mapped_file))
    assert consolidation["batch_count"] == 4
    consolidation_task_count = 0
    while True:
        batch = next_consolidation_batch(str(mapped_file), now=10_000)
        if not batch["tasks"]:
            break
        consolidation_task_count += len(batch["tasks"])
        assert len(batch["tasks"]) <= 4
        for task in batch["tasks"]:
            data = json.loads(Path(task["input_file"]).read_text(encoding="utf-8"))
            evidence_ids = [
                evidence_id
                for insight in data["local_insights"]
                for evidence_id in insight["evidence_ids"]
            ]
            Path(task["candidate_file"]).write_text(
                json.dumps(
                    {
                        "master_insights": [
                            {
                                "theme": "Product value",
                                "insight": "Satisfied with the workflow, because it works reliably",
                                "evidence_ids": evidence_ids,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            assert (
                record_consolidation_success(str(mapped_file), task["batch_id"])[
                    "status"
                ]
                == "validated"
            )
    assert consolidation_task_count == 4
    assert prepare_final_consolidation(str(mapped_file))["task_required"] is True
    final_task = next_final_consolidation(str(mapped_file), now=10_000)["task"]
    final_input = json.loads(
        Path(final_task["input_file"]).read_text(encoding="utf-8")
    )
    Path(final_task["candidate_file"]).write_text(
        json.dumps(
            {
                "master_insights": [
                    {
                        "theme": "Product value",
                        "insight": "Satisfied with the workflow, because it works reliably",
                        "evidence_ids": final_input["expected_evidence_ids"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert record_final_consolidation_success(str(mapped_file))["status"] == "validated"
    insight_result = finalize_insights(str(mapped_file))
    elapsed_seconds = time.perf_counter() - started
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert result["status"] == "success"
    assert insight_result["status"] == "success"
    assert insight_result["interviewee_count"] == 20
    assert insight_result["master_insight_count"] == 1
    assert len(insight_result["output_files"]) == 24
    assert result["total_expected"] == 20
    assert result["total_mapped"] == 20
    assert len(result["review_files"]) == 4
    assert chunked_tasks == ["user20"]
    assert elapsed_seconds < 10
    assert peak_bytes < 128 * 1024 * 1024
    headers, rows = parse_markdown_table(result["combined_file"])
    assert len(headers) == 24
    assert len(rows) == 2
    insight_data = json.loads(
        (interview / "insights-data.json").read_text(encoding="utf-8")
    )
    assert insight_data["interviewees"] == [f"user{index:02d}" for index in range(1, 21)]
    statuses = insight_data["master_insights"][0]["interviewees"]
    assert statuses["user01"]["status"] == "new"
    assert all(
        statuses[f"user{index:02d}"]["status"] == "repeated"
        for index in range(2, 21)
    )
