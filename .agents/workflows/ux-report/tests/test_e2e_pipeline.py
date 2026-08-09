import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).parents[4]
VISUALIZE = ROOT / ".agents" / "skills" / "visualize-insights" / "scripts"
SEND_EMAIL = ROOT / ".agents" / "skills" / "send-email" / "scripts"
sys.path[:0] = [str(VISUALIZE), str(SEND_EMAIL)]

from send_email import prepare_email_draft, send_approved_email  # noqa: E402
from visualize_insights import generate_report  # noqa: E402


MAPPED_TRANSCRIPT = """# Mapped Transcript

| # | Theme | Question | Observed Variable | Anh A | Chị B |
|---|---|---|---|---|---|
| 1 | Usage | What is difficult? | Friction | [00:05] Nút bấm quá nhỏ. | [00:07] Khó tìm nút bấm. |
"""

INSIGHTS = """# Compiled Insights

# Insights — Anh A
| # | Insight | Quotes |
|---|---|---|
| 1 | Nút bấm nhỏ gây khó thao tác | Nút bấm quá nhỏ. |

# Insights — Chị B
| # | Insight | Quotes |
|---|---|---|
| 1 | Nút bấm nhỏ gây khó thao tác | Khó tìm nút bấm. |

# Data Saturation Matrix
| Insight | Anh A | Chị B |
|---|---|---|
| Nút bấm nhỏ gây khó thao tác | 🔵 | 🌐 |
| **🔵 New Insights** | 1 | 0 |

## Data Saturation Chart

## Summary of Discovered Insights
- Nút bấm nhỏ gây khó thao tác.
"""


def _write_mock_dataset(project: Path) -> dict[str, object]:
    interview = project / "Interview"
    report_dir = interview / "Research Report"
    report_dir.mkdir(parents=True)
    insights_path = interview / "insights.md"
    transcript_path = interview / "mapped-transcript.md"
    full_transcript_a = interview / "transcript-Anh-A.md"
    full_transcript_b = interview / "transcript-Chị-B.md"

    insights_path.write_text(INSIGHTS, encoding="utf-8")
    transcript_path.write_text(MAPPED_TRANSCRIPT, encoding="utf-8")
    full_transcript_a.write_text("# Anh A\n\n[00:05] Nút bấm quá nhỏ.\n", encoding="utf-8")
    full_transcript_b.write_text("# Chị B\n\n[00:07] Khó tìm nút bấm.\n", encoding="utf-8")

    return {
        "insights_path": str(insights_path),
        "transcript_path": str(transcript_path),
        "full_transcript_paths": [str(full_transcript_a), str(full_transcript_b)],
        "media_paths": [],
        "output_dir": str(report_dir),
        "project_name": "UX Report",
        "open_browser": False,
    }


def test_e2e_pipeline_generates_report_and_forwards_gmail_credentials(tmp_path):
    project = tmp_path / "research-project"
    visualization = asyncio.run(generate_report(_write_mock_dataset(project)))

    assert visualization["status"] == "success"
    assert Path(visualization["output_file"]).is_file()
    assert Path(visualization["manifest_file"]).is_file()

    loaded_env = {
        "GMAIL_APP_USERNAME": "configured.sender@example.com",
        "GMAIL_APP_PASSWORD": "test-app-password",
    }
    draft = prepare_email_draft(
        visualization,
        folder_path=str(project),
        cc_recipients=["reviewer@example.com"],
        gmail_app_username=loaded_env["GMAIL_APP_USERNAME"],
    )

    assert draft["status"] == "awaiting_approval"
    assert draft["draft"]["from"] == loaded_env["GMAIL_APP_USERNAME"]
    assert draft["draft"]["to"] == []
    assert draft["draft"]["cc"] == ["reviewer@example.com"]
    assert draft["draft"]["bcc"] == []

    smtp_server = MagicMock()
    with patch("smtplib.SMTP", return_value=smtp_server):
        sent = send_approved_email(
            draft,
            approval_token=draft["approval_token"],
            gmail_app_username=loaded_env["GMAIL_APP_USERNAME"],
            gmail_app_password=loaded_env["GMAIL_APP_PASSWORD"],
        )

    assert sent["status"] == "success"
    smtp_server.login.assert_called_once_with(
        loaded_env["GMAIL_APP_USERNAME"], loaded_env["GMAIL_APP_PASSWORD"]
    )
    smtp_server.sendmail.assert_called_once()
