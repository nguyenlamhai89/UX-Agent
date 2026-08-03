import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parents[4]
MEETING_EIB = ROOT / ".agents" / "workflows" / "ux-meeting-eib"
TRANSCRIBE = MEETING_EIB / "skills" / "transcribe-audios"
SEND_EMAIL = MEETING_EIB / "skills" / "send-email"

sys.path[:0] = [
    str(TRANSCRIBE / "scripts"),
    str(SEND_EMAIL / "scripts"),
]

mock_antigravity = MagicMock()
mock_antigravity.Agent = MagicMock()
mock_antigravity.LocalAgentConfig = MagicMock()
mock_antigravity.CapabilitiesConfig = MagicMock()
sys.modules["google.antigravity"] = mock_antigravity

from send_email import prepare_email_draft, send_approved_email  # noqa: E402
from transcribe import process_file  # noqa: E402


def test_ux_meeting_e2e_pipeline(tmp_path):
    project = tmp_path / "meeting-project"
    interview = project / "Interview"
    interview.mkdir(parents=True)

    # Create dummy audio file
    audio_file = interview / "meeting_audio.mp3"
    audio_file.write_bytes(b"dummy audio content")

    # Mock transcription call
    mock_transcription_result = "[00:00] Speaker 1: Welcome to the EIB meeting.\n[00:05] Speaker 2: Let's discuss action items."
    
    with patch("transcribe.transcribe_audio", return_value=mock_transcription_result):
        res = process_file(str(audio_file), str(project), api_key="test-key")
        assert res["status"] in ("success", "skipped")

    # Ensure report HTML file is written inside Interview/
    report_dir = interview / "Research Report"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_file = report_dir / "meeting_report.html"
    report_file.write_text("<html><body>Meeting Report</body></html>", encoding="utf-8")

    # Create email payload based on transcription results
    payload = {
        "status": "success",
        "output_file": str(report_file),
        "manifest_file": str(project / "manifest.json"),
    }
    draft = prepare_email_draft(
        payload,
        folder_path=str(project),
        cc_recipients=["stakeholder@example.com"],
    )

    assert draft["status"] == "awaiting_approval"
    assert draft["draft"]["attachment_path"] == str(report_file)

    mock_server = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_server) as mock_smtp:
        # Test cancellation on missing approval token
        cancelled = send_approved_email(
            draft,
            approval_token=None,
            gmail_app_username="nguyenlamhai89@gmail.com",
            gmail_app_password="test-password",
        )
        assert cancelled["status"] == "cancelled"
        assert cancelled["error"]["code"] == "NOT_APPROVED"

        # Test successful send with valid approval token
        email_result = send_approved_email(
            draft,
            approval_token=draft["approval_token"],
            gmail_app_username="nguyenlamhai89@gmail.com",
            gmail_app_password="test-password",
        )

    assert email_result["status"] == "success"
    assert email_result["sent"] is True
    assert email_result["recipient_count"] == 1
    mock_smtp.assert_called_once()

