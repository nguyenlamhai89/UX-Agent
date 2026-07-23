import json
import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts")))

import saturate_insights
from insight_schema import SchemaError


def _quote(participant, evidence_id, text):
    return {
        "evidence_id": evidence_id,
        "participant": participant,
        "question_number": "2",
        "theme": "Product",
        "question": "What works?",
        "observed_variable": "Value",
        "timestamp": "00:15",
        "quote": text,
    }


@pytest.fixture
def insight_data(tmp_path):
    return {
        "schema_version": 2,
        "input_file": str(tmp_path / "Interview" / "mapped-transcript.md"),
        "input_signature": {"sha256": "abc123", "size": 10, "mtime_ns": 1},
        "interviewees": ["First | User", "Second User"],
        "master_insights": [
            {
                "id": 1,
                "theme": "Product value",
                "insight": "Satisfied with the workflow, because it works reliably",
                "evidence_ids": ["ev-1", "ev-2"],
                "interviewees": {
                    "First | User": {
                        "status": "new",
                        "quotes": [_quote("First | User", "ev-1", "Works | reliably")],
                    },
                    "Second User": {
                        "status": "repeated",
                        "quotes": [_quote("Second User", "ev-2", "Works for me")],
                    },
                },
            }
        ],
    }


def test_validate_schema_accepts_complete_grounded_data(insight_data):
    saturate_insights.validate_schema(insight_data)


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda data: data["master_insights"][0].pop("theme"), "theme"),
        (
            lambda data: data["master_insights"][0]["interviewees"].pop("Second User"),
            "exactly match",
        ),
        (
            lambda data: data["master_insights"][0]["interviewees"]["Second User"].update(
                {"status": "absent"}
            ),
            "cannot have quotes",
        ),
    ],
)
def test_validate_schema_rejects_incomplete_data(insight_data, mutation, match):
    mutation(insight_data)
    with pytest.raises(SchemaError, match=match):
        saturate_insights.validate_schema(insight_data)


def test_individual_report_escapes_markdown_pipes(insight_data):
    content = saturate_insights.generate_individual_report("First | User", insight_data)
    assert "Works \\| reliably" in content
    assert "Product value" in content


def test_saturation_section_preserves_interview_order_and_escapes_headers(
    insight_data, tmp_path
):
    content, chart = saturate_insights.generate_saturation_section(insight_data, str(tmp_path))
    header = next(line for line in content.splitlines() if line.startswith("| Insight"))
    assert header.index("First \\| User") < header.index("Second User")
    assert os.path.isfile(chart)


def test_saturation_chart_is_required(insight_data, tmp_path, monkeypatch):
    monkeypatch.setattr(saturate_insights, "MATPLOTLIB_AVAILABLE", False)
    with pytest.raises(saturate_insights.MissingDependencyError, match="matplotlib"):
        saturate_insights.generate_saturation_section(insight_data, str(tmp_path))


def test_render_outputs_generates_complete_auditable_set(insight_data, tmp_path):
    paths = saturate_insights.render_outputs(insight_data, str(tmp_path))
    names = {os.path.basename(path) for path in paths}
    assert {
        "insights.md",
        "insights-data.json",
        "insights-review-manifest.md",
        "saturation-chart.png",
        "all-insights-First_User.md",
        "all-insights-Second_User.md",
    } == names
    insights = (tmp_path / "insights.md").read_text(encoding="utf-8")
    assert "# Data Saturation Matrix" in insights
    assert "First \\| User" in insights
    review = (tmp_path / "insights-review-manifest.md").read_text(encoding="utf-8")
    assert "ev-1" in review
    assert "✅" in review


def test_colliding_sanitized_aliases_get_distinct_files(insight_data, tmp_path):
    insight_data["interviewees"] = ["A B", "A_B"]
    insight_data["master_insights"][0]["interviewees"] = {
        "A B": {
            "status": "new",
            "quotes": [_quote("A B", "ev-1", "Works")],
        },
        "A_B": {
            "status": "repeated",
            "quotes": [_quote("A_B", "ev-2", "Works too")],
        },
    }
    names = {
        os.path.basename(path)
        for path in saturate_insights.render_outputs(insight_data, str(tmp_path))
        if os.path.basename(path).startswith("all-insights-")
    }
    assert len(names) == 2


def test_renderer_cli_returns_structured_success(insight_data, tmp_path, capsys, monkeypatch):
    data_file = tmp_path / "data.json"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    data_file.write_text(json.dumps(insight_data), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["saturate_insights.py", str(data_file), "--output-dir", str(output_dir)],
    )
    with pytest.raises(SystemExit) as exc:
        saturate_insights.main()
    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "success"
    assert "insights.md" in payload["output_files"]


def test_load_insights_rejects_invalid_json(tmp_path):
    path = tmp_path / "invalid.json"
    path.write_text("{invalid", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid insight data JSON"):
        saturate_insights.load_insights(path)
