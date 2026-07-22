import json
from pathlib import Path

from insight_schema import file_signature


def mapped_content(interviewees):
    header = "| # | Theme | Question | Observed Variable | " + " | ".join(interviewees) + " |"
    separator = "| " + " | ".join(["---"] * (4 + len(interviewees))) + " |"
    intro = [
        f'[00:05] **<mark style="background-color: yellow;">I am {name}</mark>**'
        for name in interviewees
    ]
    product = [
        f'[00:15] **<mark style="background-color: yellow;">The workflow works for {name}</mark>**'
        for name in interviewees
    ]
    return "\n".join(
        [
            "# Mapped Transcript",
            "",
            header,
            separator,
            "| 1 | Intro | Who are you? | Identity | " + " | ".join(intro) + " |",
            "| 2 | Product | What works? | Value | " + " | ".join(product) + " |",
            "",
        ]
    )


def create_canonical(root: Path, interviewees=("user01", "user02")) -> Path:
    interview_dir = root / "Interview"
    interview_dir.mkdir(parents=True, exist_ok=True)
    mapped_file = interview_dir / "mapped-transcript.md"
    mapped_file.write_text(mapped_content(list(interviewees)), encoding="utf-8")
    mapped_path = str(mapped_file.resolve())
    mapping_manifest = {
        "version": 1,
        "status": "success",
        "canonical_current": True,
        "outputs": {
            "status": "success",
            "combined_file": mapped_path,
            "review_files": [],
            "review_manifest": str((interview_dir / "mapping-review-manifest.md").resolve()),
            "total_expected": len(interviewees),
            "total_mapped": len(interviewees),
            "failures": [],
        },
        "output_signatures": {mapped_path: file_signature(mapped_path)},
    }
    (interview_dir / "mapping-manifest.json").write_text(
        json.dumps(mapping_manifest, indent=2), encoding="utf-8"
    )
    return mapped_file.resolve()


def extraction_candidate(participant: str):
    return {
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
                        "quote": f"The workflow works for {participant}",
                    }
                ],
            }
        ],
    }


def write_extraction_candidate(task):
    Path(task["candidate_file"]).write_text(
        json.dumps(extraction_candidate(task["participant"]), indent=2),
        encoding="utf-8",
    )


def write_batch_candidate(task):
    data = json.loads(Path(task["input_file"]).read_text(encoding="utf-8"))
    evidence_ids = [
        evidence_id
        for insight in data["local_insights"]
        for evidence_id in insight["evidence_ids"]
    ]
    candidate = {
        "master_insights": [
            {
                "theme": "Product value",
                "insight": "Satisfied with the workflow, because it works reliably",
                "evidence_ids": evidence_ids,
            }
        ]
        if evidence_ids
        else []
    }
    Path(task["candidate_file"]).write_text(
        json.dumps(candidate, indent=2), encoding="utf-8"
    )


def write_final_candidate(task):
    data = json.loads(Path(task["input_file"]).read_text(encoding="utf-8"))
    candidate = {
        "master_insights": [
            {
                "theme": "Product value",
                "insight": "Satisfied with the workflow, because it works reliably",
                "evidence_ids": data["expected_evidence_ids"],
            }
        ]
    }
    Path(task["candidate_file"]).write_text(
        json.dumps(candidate, indent=2), encoding="utf-8"
    )
