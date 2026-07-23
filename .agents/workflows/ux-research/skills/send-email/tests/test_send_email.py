from copy import deepcopy
from pathlib import Path
import smtplib
import socket
import sys
from unittest.mock import MagicMock, patch

import pytest


SCRIPT_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import send_email  # noqa: E402


def _project_with_report(tmp_path, filename="Study.html"):
    project = tmp_path / "project"
    report_dir = project / "Interview" / "Research Report"
    report_dir.mkdir(parents=True)
    report = report_dir / filename
    report.write_text("<html>report</html>", encoding="utf-8")
    return project, report


def _prepare(tmp_path, **overrides):
    project, report = _project_with_report(tmp_path)
    payload = {
        "visualization_result": {"status": "success", "output_file": str(report)},
        "folder_path": str(project),
        "bcc_recipients": ["research@example.com"],
        "sender_email": "nguyenlamhai89@gmail.com",
    }
    payload.update(overrides)
    return send_email.prepare_email_draft(**payload), project, report


def test_prepare_email_draft_is_bcc_only_and_content_bound(tmp_path):
    result, _, report = _prepare(
        tmp_path,
        bcc_recipients=[" First@example.com ", "first@EXAMPLE.com", "second@example.com"],
    )

    assert result["status"] == "awaiting_approval"
    assert result["sent"] is False
    assert result["draft"]["from"] == "nguyenlamhai89@gmail.com"
    assert result["draft"]["to"] == []
    assert result["draft"]["cc"] == []
    assert result["draft"]["bcc"] == ["First@example.com", "second@example.com"]
    assert result["draft"]["attachment_path"] == str(report)
    assert "Kính gửi Quý Anh/Chị" in result["draft"]["body"]
    assert "Hướng dẫn mở báo cáo" in result["draft"]["body"]
    assert "Google Chrome" in result["draft"]["body"]
    assert result["approval_token"] == f"{send_email.APPROVAL_PREFIX}{result['draft']['draft_id']}"


def test_prepare_accepts_custom_sender_email(tmp_path):
    result, _, _ = _prepare(tmp_path, sender_email="custom.sender@example.com")
    assert result["status"] == "awaiting_approval"
    assert result["draft"]["from"] == "custom.sender@example.com"
    assert "custom.sender@example.com" in result["draft"]["body"]


def test_prepare_accepts_valid_skipped_visualization(tmp_path):
    project, report = _project_with_report(tmp_path)
    result = send_email.prepare_email_draft(
        {"status": "skipped", "output_file": str(report)},
        folder_path=str(project),
        bcc_recipients=["person@example.com"],
    )
    assert result["status"] == "awaiting_approval"


def test_prepare_accepts_report_directly_in_interview(tmp_path):
    project = tmp_path / "project"
    interview = project / "Interview"
    interview.mkdir(parents=True)
    report = interview / "DirectReport.html"
    report.write_text("<html>report</html>", encoding="utf-8")

    result = send_email.prepare_email_draft(
        {"status": "success", "output_file": str(report)},
        folder_path=str(project),
        bcc_recipients=["person@example.com"],
    )
    assert result["status"] == "awaiting_approval"
    assert result["draft"]["attachment_path"] == str(report)


@pytest.mark.parametrize(
    "recipients",
    [
        [],
        "person@example.com",
        [123],
        ["missing-at.example.com"],
        ["person@example.com\r\nBcc: attacker@example.com"],
        ["person@exa mple.com"],
        ["person@example.com\x00"],
    ],
)
def test_prepare_rejects_invalid_recipients(tmp_path, recipients):
    result, _, _ = _prepare(tmp_path, bcc_recipients=recipients)
    assert result["status"] == "error"
    assert result["error"]["code"] == "INVALID_RECIPIENTS"


def test_prepare_rejects_invalid_visualization_handoff(tmp_path):
    result, _, _ = _prepare(tmp_path, visualization_result={"status": "error"})
    assert result["error"]["code"] == "INVALID_VISUALIZATION_HANDOFF"


def test_prepare_rejects_an_unsafe_report_filename(tmp_path):
    project, report = _project_with_report(tmp_path / "unsafe", "unsafe\nreport.html")
    result = send_email.prepare_email_draft(
        {"status": "success", "output_file": str(report)},
        folder_path=str(project),
        bcc_recipients=["person@example.com"],
    )
    assert result["error"]["code"] == "INVALID_SUBJECT"


def test_prepare_rejects_relative_missing_and_wrong_extension_attachments(tmp_path):
    project, report = _project_with_report(tmp_path)
    base = {
        "folder_path": str(project),
        "bcc_recipients": ["person@example.com"],
    }
    for path in ("relative.html", str(report.with_name("missing.html")), str(report.with_suffix(".txt"))):
        result = send_email.prepare_email_draft(
            {"status": "success", "output_file": path},
            **base,
        )
        assert result["error"]["code"] == "INVALID_ATTACHMENT"


def test_prepare_rejects_directory_unreadable_and_outside_attachments(tmp_path):
    project, report = _project_with_report(tmp_path)
    outside = tmp_path / "outside.html"
    outside.write_text("outside", encoding="utf-8")

    result, _, _ = _prepare(
        tmp_path / "outside-case",
        visualization_result={"status": "success", "output_file": str(outside)},
    )
    assert result["error"]["code"] == "ATTACHMENT_OUTSIDE_REPORT_DIR"

    result, _, _ = _prepare(
        tmp_path / "directory-case",
        visualization_result={"status": "success", "output_file": str(report.parent)},
    )
    assert result["error"]["code"] == "INVALID_ATTACHMENT"

    with patch("send_email.os.access", return_value=False):
        result, _, _ = _prepare(tmp_path / "unreadable-case")
    assert result["error"]["code"] == "INVALID_ATTACHMENT"


def test_prepare_rejects_symlink_that_escapes_report_directory(tmp_path):
    project, _ = _project_with_report(tmp_path)
    outside = tmp_path / "outside.html"
    outside.write_text("outside", encoding="utf-8")
    link = project / "Interview" / "Research Report" / "linked.html"
    link.symlink_to(outside)
    result = send_email.prepare_email_draft(
        {"status": "success", "output_file": str(link)},
        folder_path=str(project),
        bcc_recipients=["person@example.com"],
    )
    assert result["error"]["code"] == "ATTACHMENT_OUTSIDE_REPORT_DIR"


def test_send_requires_exact_approval_without_smtp_call(tmp_path):
    draft, _, _ = _prepare(tmp_path)
    with patch("smtplib.SMTP") as mock_smtp:
        missing = send_email.send_approved_email(
            draft,
            approval_token=None,
            gmail_app_username="user@example.com",
            gmail_app_password="pwd",
        )
        ambiguous = send_email.send_approved_email(
            draft,
            approval_token="approved",
            gmail_app_username="user@example.com",
            gmail_app_password="pwd",
        )
    assert missing["status"] == "cancelled"
    assert ambiguous["error"]["code"] == "NOT_APPROVED"
    mock_smtp.assert_not_called()


def test_send_rejects_modified_draft_without_smtp_call(tmp_path):
    draft, _, _ = _prepare(tmp_path)
    modified = deepcopy(draft)
    modified["draft"]["subject"] = "Changed"
    with patch("smtplib.SMTP") as mock_smtp:
        result = send_email.send_approved_email(
            modified,
            approval_token=modified["approval_token"],
            gmail_app_username="user@example.com",
            gmail_app_password="pwd",
        )
    assert result["error"]["code"] == "INVALID_INPUT"
    mock_smtp.assert_not_called()


def test_send_requires_gmail_credentials(tmp_path):
    draft, _, _ = _prepare(tmp_path)
    with patch("smtplib.SMTP") as mock_smtp:
        missing_pwd = send_email.send_approved_email(
            draft,
            approval_token=draft["approval_token"],
            gmail_app_username="user@example.com",
            gmail_app_password="",
        )
    assert missing_pwd["error"]["code"] == "GMAIL_CONFIG_MISSING"
    mock_smtp.assert_not_called()


def test_successful_send_via_smtp(tmp_path):
    draft, _, report = _prepare(
        tmp_path,
        bcc_recipients=["one@example.com", "two@example.com"],
        sender_email="sender@example.com",
    )

    mock_server = MagicMock()
    with patch("smtplib.SMTP", return_value=mock_server) as mock_smtp_class:
        result = send_email.send_approved_email(
            draft,
            approval_token=draft["approval_token"],
            gmail_app_username="sender@example.com",
            gmail_app_password="app-password-123",
            timeout_seconds=15.0,
        )

    assert result == {
        "status": "success",
        "sent": True,
        "sender": "sender@example.com",
        "recipient_count": 2,
        "attachment_path": str(report),
    }

    mock_smtp_class.assert_called_once_with("smtp.gmail.com", 587, timeout=15.0)
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("sender@example.com", "app-password-123")
    mock_server.sendmail.assert_called_once()

    sendmail_args = mock_server.sendmail.call_args[0]
    assert sendmail_args[0] == "sender@example.com"
    assert sendmail_args[1] == ["one@example.com", "two@example.com"]
    raw_msg = sendmail_args[2]
    assert "To:" not in raw_msg
    assert "Bcc:" not in raw_msg
    assert "From: sender@example.com" in raw_msg
    assert "Subject: =?utf-8?" in raw_msg
    mock_server.quit.assert_called_once()


@pytest.mark.parametrize(
    ("side_effect", "code"),
    [
        (smtplib.SMTPAuthenticationError(535, b"Authentication failed"), "SMTP_AUTH_FAILED"),
        (socket.timeout(), "SEND_TIMEOUT"),
        (smtplib.SMTPException("SMTP Failure"), "SMTP_SEND_FAILED"),
    ],
)
def test_send_maps_smtp_failures(tmp_path, side_effect, code):
    draft, _, _ = _prepare(tmp_path)
    mock_server = MagicMock()
    mock_server.login.side_effect = side_effect
    mock_server.sendmail.side_effect = side_effect

    with patch("smtplib.SMTP", return_value=mock_server):
        result = send_email.send_approved_email(
            draft,
            approval_token=draft["approval_token"],
            gmail_app_username="sender@example.com",
            gmail_app_password="wrong-password",
        )

    assert result["status"] == "error"
    assert result["sent"] is False
    assert result["error"]["code"] == code
