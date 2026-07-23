from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

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
    assert result["draft"]["from"] == send_email.SENDER_EMAIL
    assert result["draft"]["to"] == []
    assert result["draft"]["cc"] == []
    assert result["draft"]["bcc"] == ["First@example.com", "second@example.com"]
    assert result["draft"]["attachment_path"] == str(report)
    assert "Kính gửi Quý Anh/Chị" in result["draft"]["body"]
    assert "Hướng dẫn mở báo cáo" in result["draft"]["body"]
    assert "Google Chrome" in result["draft"]["body"]
    assert result["approval_token"] == f"{send_email.APPROVAL_PREFIX}{result['draft']['draft_id']}"


def test_prepare_accepts_valid_skipped_visualization(tmp_path):
    project, report = _project_with_report(tmp_path)
    result = send_email.prepare_email_draft(
        {"status": "skipped", "output_file": str(report)},
        folder_path=str(project),
        bcc_recipients=["person@example.com"],
    )
    assert result["status"] == "awaiting_approval"


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


def test_send_requires_exact_approval_without_invoking_subprocess(tmp_path):
    draft, _, _ = _prepare(tmp_path)
    with patch("send_email.subprocess.run") as run:
        missing = send_email.send_approved_email(draft, approval_token=None)
        ambiguous = send_email.send_approved_email(draft, approval_token="approved")
    assert missing["status"] == "cancelled"
    assert ambiguous["error"]["code"] == "NOT_APPROVED"
    run.assert_not_called()


def test_send_rejects_modified_draft_without_invoking_subprocess(tmp_path):
    draft, _, _ = _prepare(tmp_path)
    modified = deepcopy(draft)
    modified["draft"]["subject"] = "Changed"
    with patch("send_email.subprocess.run") as run:
        result = send_email.send_approved_email(
            modified,
            approval_token=modified["approval_token"],
        )
    assert result["error"]["code"] == "INVALID_INPUT"
    run.assert_not_called()


def test_send_revalidates_bcc_only_and_timeout_before_subprocess(tmp_path):
    draft, _, _ = _prepare(tmp_path)
    for mutation in ("to", "cc"):
        changed = deepcopy(draft)
        changed["draft"][mutation] = ["person@example.com"]
        with patch("send_email.subprocess.run") as run:
            result = send_email.send_approved_email(
                changed,
                approval_token=changed["approval_token"],
            )
        assert result["error"]["code"] == "INVALID_INPUT"
        run.assert_not_called()

    with patch("send_email.subprocess.run") as run:
        result = send_email.send_approved_email(
            draft,
            approval_token=draft["approval_token"],
            timeout_seconds=0,
        )
    assert result["error"]["code"] == "INVALID_INPUT"
    run.assert_not_called()


def test_successful_send_uses_static_argv_boundary_once(tmp_path):
    draft, _, report = _prepare(
        tmp_path,
        bcc_recipients=["one@example.com", "two@example.com"],
    )
    completed = subprocess.CompletedProcess([], 0, stdout="SENT\n", stderr="")
    with patch("send_email.subprocess.run", return_value=completed) as run:
        result = send_email.send_approved_email(
            draft,
            approval_token=draft["approval_token"],
            timeout_seconds=15,
        )

    assert result == {
        "status": "success",
        "sent": True,
        "sender": send_email.SENDER_EMAIL,
        "recipient_count": 2,
        "attachment_path": str(report),
    }
    run.assert_called_once()
    args, kwargs = run.call_args
    command = args[0]
    assert command[:4] == [
        send_email.OSASCRIPT_PATH,
        "-e",
        send_email.STATIC_APPLESCRIPT,
        "--",
    ]
    assert command[4:] == [
        send_email.SENDER_EMAIL,
        draft["draft"]["subject"],
        draft["draft"]["body"],
        str(report),
        "one@example.com",
        "two@example.com",
    ]
    assert send_email.SENDER_EMAIL not in send_email.STATIC_APPLESCRIPT
    assert "one@example.com" not in send_email.STATIC_APPLESCRIPT
    assert "make new bcc recipient" in send_email.STATIC_APPLESCRIPT
    assert "sender:senderAddress" in send_email.STATIC_APPLESCRIPT
    assert "make new to recipient" not in send_email.STATIC_APPLESCRIPT
    assert "make new cc recipient" not in send_email.STATIC_APPLESCRIPT
    assert kwargs == {
        "shell": False,
        "check": False,
        "capture_output": True,
        "text": True,
        "timeout": 15.0,
    }


@pytest.mark.parametrize(
    ("side_effect", "completed", "code"),
    [
        (FileNotFoundError(), None, "OSASCRIPT_NOT_FOUND"),
        (subprocess.TimeoutExpired("osascript", 30), None, "SEND_TIMEOUT"),
        (None, subprocess.CompletedProcess([], 1, stdout="", stderr="Not authorized (-1743)"), "MAIL_AUTOMATION_DENIED"),
        (None, subprocess.CompletedProcess([], 1, stdout="", stderr="Mail failed"), "MAIL_SEND_FAILED"),
        (None, subprocess.CompletedProcess([], 0, stdout="unknown", stderr=""), "UNEXPECTED_OSASCRIPT_OUTPUT"),
    ],
)
def test_send_maps_mail_failures_without_retry(tmp_path, side_effect, completed, code):
    draft, _, _ = _prepare(tmp_path)
    with patch("send_email.subprocess.run", side_effect=side_effect, return_value=completed) as run:
        result = send_email.send_approved_email(
            draft,
            approval_token=draft["approval_token"],
        )
    assert result["status"] == "error"
    assert result["sent"] is False
    assert result["error"]["code"] == code
    run.assert_called_once()


def test_send_rejects_a_modified_sender_without_invoking_subprocess(tmp_path):
    draft, _, _ = _prepare(tmp_path)
    draft["draft"]["from"] = "other@example.com"
    with patch("send_email.subprocess.run") as run:
        result = send_email.send_approved_email(
            draft,
            approval_token=draft["approval_token"],
        )
    assert result["error"]["code"] == "INVALID_INPUT"
    run.assert_not_called()


def test_send_reports_missing_configured_sender_account(tmp_path):
    draft, _, _ = _prepare(tmp_path)
    completed = subprocess.CompletedProcess([], 1, stdout="", stderr="Cannot set sender")
    with patch("send_email.subprocess.run", return_value=completed):
        result = send_email.send_approved_email(
            draft,
            approval_token=draft["approval_token"],
        )
    assert result["error"]["code"] == "SENDER_ACCOUNT_NOT_CONFIGURED"
