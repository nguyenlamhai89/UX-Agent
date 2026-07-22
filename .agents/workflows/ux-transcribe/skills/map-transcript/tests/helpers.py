from pathlib import Path


QUESTIONNAIRE_CONTENT = """# Questionnaire

| # | Theme | Question | Observed Variable |
|---|-------|----------|-------------------|
| 1 | Warm-up | Please introduce yourself | Name |
| 1 | Warm-up | Please introduce yourself | Age |
| 2 | Product | What do you think about product X | First Impression |
| 3 | Closing | Any final thoughts | Feedback |
"""


def transcript_content(alias: str) -> str:
    return f"""# Interview Transcript

[00:00] Interviewer: Please introduce yourself.
[00:05] Interviewee: My name is {alias} and I am 25 years old.
[01:00] Interviewer: What do you think about product X?
[01:10] Interviewee: I think it looks useful.
[02:00] Interviewer: Any final thoughts?
[02:10] Interviewee: No additional thoughts.
"""


def mapped_content(
    alias: str,
    *,
    first_response: str | None = None,
    summary_total: int = 4,
    coverage_end: str = "[02:10]",
) -> str:
    first = first_response or (
        f'[00:05] **<mark style="background-color: yellow;">My name is {alias}</mark>**'
    )
    return f"""# Mapped Transcript

| # | Theme | Question | Observed Variable | {alias} |
|---|-------|----------|-------------------|---|
| 1 | Warm-up | Please introduce yourself | Name | {first} |
| 1 | Warm-up | Please introduce yourself | Age | [00:05] **<mark style="background-color: yellow;">I am 25 years old</mark>** |
| 2 | Product | What do you think about product X | First Impression | [01:10] **<mark style="background-color: yellow;">It looks useful</mark>** |
| 3 | Closing | Any final thoughts | Feedback | N/A |

> **Mapping Summary**: Total rows: {summary_total} | Answered: 3 | N/A: 1 | Transcript coverage: [00:00] to {coverage_end}
"""


def create_study(root: Path, count: int = 2) -> Path:
    interview = root / "Interview"
    interview.mkdir(parents=True)
    (interview / "full-questionnaire.md").write_text(
        QUESTIONNAIRE_CONTENT,
        encoding="utf-8",
    )
    for index in range(1, count + 1):
        name = f"user{index:02d}"
        (interview / f"transcript_{name}.md").write_text(
            transcript_content(name),
            encoding="utf-8",
        )
    return interview


def write_mapped(interview: Path, audio_name: str, alias: str | None = None) -> Path:
    path = interview / f"mapped-transcript-{audio_name}.md"
    path.write_text(mapped_content(alias or audio_name), encoding="utf-8")
    return path
