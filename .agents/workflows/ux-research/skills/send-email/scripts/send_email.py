"""Prepare and send approved BCC-only Gmail SMTP messages from a configured sender."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import smtplib
import socket
from typing import Any


APPROVAL_PREFIX = "APPROVE-SEND-EMAIL:"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
import unicodedata

AFFIRMATIVE_TOKENS = {
    unicodedata.normalize("NFC", token)
    for token in {"ok", "yes", "approved", "y", "gui", "gửi", "approve", "confirm", "đồng ý", "dong y"}
}




class ValidationError(ValueError):
    """Represent a stable, user-safe validation failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _error(code: str, message: str, *, status: str = "error") -> dict[str, Any]:
    return {
        "status": status,
        "sent": False,
        "error": {"code": code, "message": message},
    }


def _validate_folder_path(folder_path: str) -> Path:
    if not isinstance(folder_path, str) or not folder_path.strip():
        raise ValidationError("INVALID_INPUT", "folder_path must be a non-empty absolute path.")
    path = Path(folder_path)
    if not path.is_absolute():
        raise ValidationError("INVALID_INPUT", "folder_path must be an absolute path.")
    return path.resolve(strict=False)


def _validate_sender_email(sender_email: Any) -> str:
    if not isinstance(sender_email, str) or not sender_email.strip():
        raise ValidationError("INVALID_INPUT", "sender_email / GMAIL_APP_USERNAME is required.")
    address = sender_email.strip()
    if _contains_control(address) or any(character.isspace() for character in address):
        raise ValidationError("INVALID_INPUT", "sender_email must be a valid email address.")
    display_name, parsed = parseaddr(address)
    if display_name or parsed != address or address.count("@") != 1:
        raise ValidationError("INVALID_INPUT", "sender_email must be a valid email address.")
    local_part, domain = address.rsplit("@", 1)
    if (
        not local_part
        or not domain
        or local_part.startswith(".")
        or local_part.endswith(".")
        or ".." in local_part
        or domain.startswith(".")
        or domain.endswith(".")
        or ".." in domain
    ):
        raise ValidationError("INVALID_INPUT", "sender_email must be a valid email address.")
    return address


def _validate_attachment(
    attachment_path: Any,
    *,
    report_dir: Path | None = None,
) -> str:
    if not isinstance(attachment_path, str) or not attachment_path.strip():
        raise ValidationError("INVALID_ATTACHMENT", "The HTML attachment path is required.")

    candidate = Path(attachment_path)
    if not candidate.is_absolute():
        raise ValidationError("INVALID_ATTACHMENT", "The HTML attachment path must be absolute.")
    if candidate.suffix.lower() != ".html":
        raise ValidationError("INVALID_ATTACHMENT", "The attachment must be an HTML file.")

    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError):
        raise ValidationError("INVALID_ATTACHMENT", "The HTML attachment does not exist or cannot be resolved.")

    if not resolved.is_file() or not os.access(resolved, os.R_OK):
        raise ValidationError("INVALID_ATTACHMENT", "The HTML attachment must be a readable regular file.")

    if report_dir is not None:
        expected_dir = report_dir.resolve(strict=False)
        if not resolved.is_relative_to(expected_dir):
            raise ValidationError(
                "ATTACHMENT_OUTSIDE_REPORT_DIR",
                "The HTML attachment must remain inside Interview/Research Report.",
            )
    elif resolved.parent.name not in ("Research Report", "Interview") and resolved.parent.parent.name != "Interview":
        raise ValidationError(
            "ATTACHMENT_OUTSIDE_REPORT_DIR",
            "The HTML attachment must remain inside Interview/Research Report.",
        )

    return attachment_path


def _contains_control(value: str, *, allow_body_whitespace: bool = False) -> bool:
    allowed = {9, 10, 13} if allow_body_whitespace else set()
    return any((ord(character) < 32 and ord(character) not in allowed) or ord(character) == 127 for character in value)


def _normalize_recipients(recipients: Any) -> list[str]:
    if isinstance(recipients, (str, bytes)) or not isinstance(recipients, Sequence):
        raise ValidationError("INVALID_RECIPIENTS", "bcc_recipients must be a non-empty list of email addresses.")

    normalized: list[str] = []
    seen: set[str] = set()
    for recipient in recipients:
        if not isinstance(recipient, str):
            raise ValidationError("INVALID_RECIPIENTS", "Every BCC recipient must be a string email address.")
        address = recipient.strip()
        if not address or _contains_control(address) or any(character.isspace() for character in address):
            raise ValidationError("INVALID_RECIPIENTS", "Every BCC recipient must be a valid email address.")
        display_name, parsed = parseaddr(address)
        if display_name or parsed != address or address.count("@") != 1:
            raise ValidationError("INVALID_RECIPIENTS", "Every BCC recipient must be a valid email address.")
        local_part, domain = address.rsplit("@", 1)
        if (
            not local_part
            or not domain
            or local_part.startswith(".")
            or local_part.endswith(".")
            or ".." in local_part
            or domain.startswith(".")
            or domain.endswith(".")
            or ".." in domain
        ):
            raise ValidationError("INVALID_RECIPIENTS", "Every BCC recipient must be a valid email address.")
        dedupe_key = address.casefold()
        if dedupe_key not in seen:
            seen.add(dedupe_key)
            normalized.append(address)

    if not normalized:
        raise ValidationError("INVALID_RECIPIENTS", "At least one BCC recipient is required.")
    return normalized


def _validate_subject(subject: Any) -> str:
    if not isinstance(subject, str) or not subject.strip() or _contains_control(subject):
        raise ValidationError("INVALID_SUBJECT", "The subject must be non-empty and contain no control characters.")
    return subject.strip()


def _validate_body(body: Any) -> str:
    if not isinstance(body, str) or not body.strip() or _contains_control(body, allow_body_whitespace=True):
        raise ValidationError("INVALID_BODY", "The email body must be non-empty and contain no unsafe control characters.")
    return body


def build_formal_email_content(report_filename: str, sender_email: str = "nguyenlamhai89@gmail.com") -> tuple[str, str]:
    """Create the fixed professional Vietnamese email content for a report attachment."""

    report_label = (
        Path(report_filename).stem.replace("_", " ").strip()
        or "Báo cáo UX Research"
    )
    subject = f"[Báo cáo UX Research] {report_label}"
    body = (
        "Kính gửi Quý Anh/Chị,\n\n"
        f"Xin gửi Quý Anh/Chị báo cáo nghiên cứu trải nghiệm người dùng “{report_label}”. "
        "File báo cáo HTML đã được đính kèm trong email này.\n\n"
        "Hướng dẫn mở báo cáo:\n"
        "1. Tải file HTML đính kèm về máy tính.\n"
        "2. Nhấp đúp vào file hoặc mở file bằng Google Chrome, Microsoft Edge, hoặc Safari.\n"
        "3. Để có trải nghiệm tốt nhất, vui lòng sử dụng phiên bản trình duyệt mới nhất.\n\n"
        "Trân trọng,\n"
        "UX Research Team\n"
        f"{sender_email}"
    )
    return subject, body


def _canonical_fields(draft: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "from": draft["from"],
        "to": draft["to"],
        "cc": draft["cc"],
        "bcc": draft["bcc"],
        "subject": draft["subject"],
        "body": draft["body"],
        "attachment_path": draft["attachment_path"],
    }


def _draft_id(draft: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        _canonical_fields(draft),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def prepare_email_draft(
    visualization_result: Mapping[str, Any],
    *,
    folder_path: str,
    bcc_recipients: Sequence[str],
    sender_email: str = "nguyenlamhai89@gmail.com",
) -> dict[str, Any]:
    """Validate an email draft and return the exact approval token required to send it."""

    try:
        if not isinstance(visualization_result, Mapping):
            raise ValidationError("INVALID_VISUALIZATION_HANDOFF", "visualization_result must be a mapping.")
        if visualization_result.get("status") not in {"success", "skipped"}:
            raise ValidationError(
                "INVALID_VISUALIZATION_HANDOFF",
                "Visualization must complete successfully before email drafting.",
            )
        if "output_file" not in visualization_result:
            raise ValidationError(
                "INVALID_VISUALIZATION_HANDOFF",
                "Visualization output_file is required for email drafting.",
            )

        validated_sender = _validate_sender_email(sender_email)
        project_dir = _validate_folder_path(folder_path)
        attachment_path = _validate_attachment(
            visualization_result["output_file"],
            report_dir=project_dir / "Interview",
        )
        recipients = _normalize_recipients(bcc_recipients)
        generated_subject, generated_body = build_formal_email_content(
            Path(attachment_path).name,
            validated_sender,
        )
        validated_subject = _validate_subject(generated_subject)
        validated_body = _validate_body(generated_body)

        draft: dict[str, Any] = {
            "from": validated_sender,
            "to": [],
            "cc": [],
            "bcc": recipients,
            "subject": validated_subject,
            "body": validated_body,
            "attachment_path": attachment_path,
        }
        identifier = _draft_id(draft)
        draft["draft_id"] = identifier
        return {
            "status": "awaiting_approval",
            "sent": False,
            "draft": draft,
            "approval_token": f"{APPROVAL_PREFIX}{identifier}",
        }
    except ValidationError as error:
        return _error(error.code, error.message)
    except Exception:
        return _error("INTERNAL_ERROR", "The email draft could not be prepared.")


def _validate_draft_result(draft_result: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    if not isinstance(draft_result, Mapping) or draft_result.get("status") != "awaiting_approval":
        raise ValidationError("INVALID_INPUT", "An intact awaiting_approval draft is required.")
    draft = draft_result.get("draft")
    if not isinstance(draft, Mapping):
        raise ValidationError("INVALID_INPUT", "The draft payload is missing or invalid.")
    if draft.get("to") != [] or draft.get("cc") != []:
        raise ValidationError("INVALID_INPUT", "To and CC must remain empty.")
    sender = _validate_sender_email(draft.get("from"))

    recipients = _normalize_recipients(draft.get("bcc"))
    if recipients != draft.get("bcc"):
        raise ValidationError("INVALID_INPUT", "The BCC recipient list was modified or is not normalized.")
    subject = _validate_subject(draft.get("subject"))
    body = _validate_body(draft.get("body"))
    attachment_path = _validate_attachment(draft.get("attachment_path"))

    validated = {
        "from": sender,
        "to": [],
        "cc": [],
        "bcc": recipients,
        "subject": subject,
        "body": body,
        "attachment_path": attachment_path,
    }
    identifier = _draft_id(validated)
    expected_token = f"{APPROVAL_PREFIX}{identifier}"
    if draft.get("draft_id") != identifier or draft_result.get("approval_token") != expected_token:
        raise ValidationError("INVALID_INPUT", "The approved draft was modified and must be prepared again.")
    return validated, expected_token


def _send_via_smtp(
    draft: dict[str, Any],
    app_username: str,
    app_password: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Internal helper to dispatch email using Python smtplib."""
    from email.header import Header

    msg = MIMEMultipart()
    msg["From"] = draft["from"]
    msg["Subject"] = Header(draft["subject"], "utf-8")
    msg.attach(MIMEText(draft["body"], "plain", "utf-8"))

    attachment_path = Path(draft["attachment_path"])
    try:
        with open(attachment_path, "rb") as f:
            part = MIMEBase("text", "html", charset="utf-8")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=attachment_path.name,
        )
        msg.attach(part)
    except OSError:
        return _error("INVALID_ATTACHMENT", "The HTML attachment file could not be read.")

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=timeout_seconds)
        try:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(app_username, app_password)
            # Deliver to BCC list without setting To/Bcc headers in msg
            server.sendmail(app_username, draft["bcc"], msg.as_string())
        finally:
            try:
                server.quit()
            except Exception:
                pass
    except smtplib.SMTPAuthenticationError:
        return _error(
            "SMTP_AUTH_FAILED",
            "Gmail authentication failed. Please check GMAIL_APP_USERNAME and GMAIL_APP_PASSWORD.",
        )
    except (socket.timeout, TimeoutError):
        return _error(
            "SEND_TIMEOUT",
            "Gmail SMTP server connection timed out; the message was not retried.",
        )
    except (smtplib.SMTPException, OSError) as e:
        return _error(
            "SMTP_SEND_FAILED",
            f"Failed to send email via Gmail SMTP: {e}",
        )

    return {
        "status": "success",
        "sent": True,
        "sender": draft["from"],
        "recipient_count": len(draft["bcc"]),
        "attachment_path": draft["attachment_path"],
    }


def send_approved_email(
    draft_result: Mapping[str, Any],
    *,
    approval_token: str | None,
    gmail_app_username: str | None = None,
    gmail_app_password: str | None = None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Send an intact draft exactly once via Gmail SMTP after its content-bound token is approved."""

    try:
        draft, expected_token = _validate_draft_result(draft_result)
        is_exact = isinstance(approval_token, str) and hmac.compare_digest(
            approval_token.encode("utf-8"), expected_token.encode("utf-8")
        )
        is_affirmative = (
            isinstance(approval_token, str)
            and unicodedata.normalize("NFC", approval_token.strip().lower()) in AFFIRMATIVE_TOKENS
        )
        if not (is_exact or is_affirmative):
            return _error("NOT_APPROVED", "Neither the exact approval token nor an affirmative confirmation keyword ('ok', 'yes', 'gửi', etc.) was provided.", status="cancelled")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        ):
            raise ValidationError("INVALID_INPUT", "timeout_seconds must be a positive finite number.")

        username = (gmail_app_username or draft["from"]).strip()
        password = (gmail_app_password or "").strip()

        if not username or not password:
            return _error(
                "GMAIL_CONFIG_MISSING",
                "Both GMAIL_APP_USERNAME and GMAIL_APP_PASSWORD must be configured in .env to send emails.",
            )

        return _send_via_smtp(draft, username, password, float(timeout_seconds))
    except ValidationError as error:
        return _error(error.code, error.message)
    except Exception:
        return _error("INTERNAL_ERROR", "The email could not be sent.")
