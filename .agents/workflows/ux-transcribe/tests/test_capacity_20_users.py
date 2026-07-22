import sys
import time
import tracemalloc
from pathlib import Path


SCRIPTS = Path(__file__).parent.parent / "skills" / "map-transcript" / "scripts"
sys.path.append(str(SCRIPTS))

from map_transcript import parse_markdown_table  # noqa: E402
from mapping_pipeline import (  # noqa: E402
    finalize_pipeline,
    next_batch,
    prepare_pipeline,
    record_success,
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


def _mapped(alias):
    return f"""# Mapped Transcript

| # | Theme | Question | Observed Variable | {alias} |
|---|---|---|---|---|
| 1 | Intro | Who are you? | Identity | [00:05] **<mark style="background-color: yellow;">I am {alias}</mark>** |
| 2 | Product | What works? | Value | [00:15] **<mark style="background-color: yellow;">The workflow works</mark>** |

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
            )
        (interview / f"transcript_{alias}.md").write_text(
            content,
            encoding="utf-8",
        )

    tracemalloc.start()
    started = time.perf_counter()
    prepared = prepare_pipeline(
        str(tmp_path),
        max_workers=4,
        max_tokens=100,
        review_batch_size=5,
    )
    assert prepared["counts"] == {"pending": 20}
    batch_sizes = []
    chunked_tasks = []
    while True:
        batch = next_batch(str(tmp_path), now=10_000)
        if not batch["tasks"]:
            break
        batch_sizes.append(len(batch["tasks"]))
        chunked_tasks.extend(
            task["audio_name"] for task in batch["tasks"] if task["chunked"]
        )
        for task in batch["tasks"]:
            Path(task["candidate_file"]).write_text(
                _mapped(task["audio_name"]),
                encoding="utf-8",
            )
            assert (
                record_success(str(tmp_path), task["audio_name"])["status"]
                == "validated"
            )

    assert batch_sizes == [4, 4, 4, 4, 4]
    result = finalize_pipeline(str(tmp_path))
    elapsed_seconds = time.perf_counter() - started
    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert result["status"] == "success"
    assert result["total_expected"] == 20
    assert result["total_mapped"] == 20
    assert len(result["review_files"]) == 4
    assert chunked_tasks == ["user20"]
    assert elapsed_seconds < 5
    assert peak_bytes < 128 * 1024 * 1024
    headers, rows = parse_markdown_table(result["combined_file"])
    assert len(headers) == 24
    assert len(rows) == 2
