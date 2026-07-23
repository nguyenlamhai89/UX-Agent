"""Prepare and send approved BCC-only Apple Mail messages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from email.utils import parseaddr
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import subprocess
from typing import Any


APPROVAL_PREFIX = "APPROVE-SEND-EMAIL:"
OSASCRIPT_PATH = "/usr/bin/osascript"
SUCCESS_MARKER = "SENT"

STATIC_APPLESCRIPT = r'''
on run argv
    if (count of argv) < 4 then error "Missing email arguments"

    set subjectText to item 1 of argv
    set bodyText to item 2 of argv
    set attachmentPath to item 3 of argv
    set bccAddresses to items 4 thru -1 of argv

    tell application "Mail"
        set outgoingMessage to make new outgoing message with properties ¬
            {subject:subjectText, content:bodyText, visible:false}

        tell outgoingMessage
            repeat with addressText in bccAddresses
                make new bcc recipient at end of bcc recipients with properties ¬
                    {address:(contents of addressText)}
            end repeat

            make new attachment with properties ¬
                {file name:(POSIX file attachmentPath)} at after last paragraph
            send
        end tell
    end tell

    return "SENT"
end run
'''.strip()


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
    elif resolved.parent.name != "Research Report" or resolved.parent.parent.name != "Interview":
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


def _canonical_fields(draft: Mapping[str, Any]) -> dict[str, Any]:
    return {
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
    subject: str,
    body: str,
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

        project_dir = _validate_folder_path(folder_path)
        attachment_path = _validate_attachment(
            visualization_result["output_file"],
            report_dir=project_dir / "Interview" / "Research Report",
        )
        recipients = _normalize_recipients(bcc_recipients)
        validated_subject = _validate_subject(subject)
        validated_body = _validate_body(body)

        draft: dict[str, Any] = {
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

    recipients = _normalize_recipients(draft.get("bcc"))
    if recipients != draft.get("bcc"):
        raise ValidationError("INVALID_INPUT", "The BCC recipient list was modified or is not normalized.")
    subject = _validate_subject(draft.get("subject"))
    body = _validate_body(draft.get("body"))
    attachment_path = _validate_attachment(draft.get("attachment_path"))

    validated = {
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


def send_approved_email(
    draft_result: Mapping[str, Any],
    *,
    approval_token: str | None,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Send an intact draft exactly once after its content-bound token is approved."""

    try:
        draft, expected_token = _validate_draft_result(draft_result)
        if not isinstance(approval_token, str) or not hmac.compare_digest(approval_token, expected_token):
            return _error("NOT_APPROVED", "The exact approval token was not provided.", status="cancelled")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or timeout_seconds <= 0
        ):
            raise ValidationError("INVALID_INPUT", "timeout_seconds must be a positive finite number.")

        command = [
            OSASCRIPT_PATH,
            "-e",
            STATIC_APPLESCRIPT,
            "--",
            draft["subject"],
            draft["body"],
            draft["attachment_path"],
            *draft["bcc"],
        ]
        try:
            completed = subprocess.run(
                command,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                timeout=float(timeout_seconds),
            )
        except FileNotFoundError:
            return _error("OSASCRIPT_NOT_FOUND", "AppleScript is not available on this system.")
        except subprocess.TimeoutExpired:
            return _error(
                "SEND_TIMEOUT",
                "Apple Mail did not confirm the send before the timeout; the message was not retried.",
            )
        except OSError:
            return _error("MAIL_SEND_FAILED", "Apple Mail could not be started.")

        if completed.returncode != 0:
            diagnostic = f"{completed.stderr}\n{completed.stdout}".casefold()
            if any(marker in diagnostic for marker in ("-1743", "not authorized", "not permitted", "automation denied")):
                return _error(
                    "MAIL_AUTOMATION_DENIED",
                    "macOS denied permission to control Apple Mail. Allow automation access and try again.",
                )
            return _error("MAIL_SEND_FAILED", "Apple Mail did not send the message.")
        if completed.stdout.strip() != SUCCESS_MARKER:
            return _error(
                "UNEXPECTED_OSASCRIPT_OUTPUT",
                "Apple Mail did not return an unambiguous send confirmation; the message was not retried.",
            )

        return {
            "status": "success",
            "sent": True,
            "recipient_count": len(draft["bcc"]),
            "attachment_path": draft["attachment_path"],
        }
    except ValidationError as error:
        return _error(error.code, error.message)
    except Exception:
        return _error("INTERNAL_ERROR", "The email could not be sent.")
