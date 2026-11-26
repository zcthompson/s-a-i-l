"""Email delivery for persisted notification rows; best-effort.

A mail failure must never break or abort the primary operation.
"""

import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.models.use_case import User
from backend.services.config_service import effective_email_settings

logger = logging.getLogger(__name__)

TYPE_LABELS = {
    "mention": "Mention",
    "comment_added": "New comment",
    "status_change": "Status changed",
    "scoring": "Score updated",
    "customer_shared": "Customer shared",
    "task_assigned": "Task assigned",
    "task_reassigned": "Task reassigned",
    "task_completed": "Task completed",
    "task_due_soon": "Task due soon",
    "task_overdue": "Task overdue",
}


def _label(notification_type: str) -> str:
    return TYPE_LABELS.get(notification_type, notification_type)


def build_message(notification) -> EmailMessage:
    """Deterministic plain-text mail for one notification row (no timestamp)."""
    msg = EmailMessage()
    msg["Subject"] = f"S-A-I-L: {_label(notification.type)}"
    msg.set_content(f"{notification.message}\n\nSent by S-A-I-L (Sales Analytics and Intelligence Launchpad).")
    return msg


def _connect(host, port, security):
    """smtplib seam — the ONLY smtplib entry point."""
    if security == "ssl":
        return smtplib.SMTP_SSL(host, port)
    if security == "none":
        return smtplib.SMTP(host, port)
    return smtplib.SMTP(host, port)


def send_message(eff, msg):
    """Send using effective settings; propagate failures to the caller."""
    conn = _connect((eff.get("smtp_host") or "").strip(),
                    int(eff.get("smtp_port") or 587), eff.get("smtp_security") or "starttls")
    try:
        if (eff.get("smtp_security") or "starttls") == "starttls":
            conn.starttls()
        if eff.get("smtp_username"):
            conn.login(eff["smtp_username"], get_settings().email_smtp_password or "")
        conn.send_message(msg)
    finally:
        try:
            conn.quit()
        except Exception:
            pass


def delivery_ready(eff: dict) -> bool:
    """Pure config check (no DB query): enabled + host + from_address."""
    return bool(eff.get("enabled")
                and (eff.get("smtp_host") or "").strip()
                and (eff.get("from_address") or "").strip())


def deliver_notification_email(db: Session, notification, eff: dict | None = None,
                               recipient_email: str | None = None) -> str:
    """Best-effort send: sent, skipped_not_configured, skipped_no_recipient_email, failed.

    ``eff`` — effective settings pre-read by the caller (the fan-out path
    reads them exactly once); read here when omitted.
    ``recipient_email`` — the recipient's address pre-resolved by the caller
    (the fan-out path resolves addresses in the recipient query itself);
    the recipient's User row is looked up here when omitted.
    """
    try:
        if eff is None:
            eff = effective_email_settings(db)
        if not delivery_ready(eff):
            return "skipped_not_configured"
        if recipient_email is None:
            user = db.query(User).filter(User.username == notification.user_name, User.is_active == 1).first()
            if user is None or not (user.email or "").strip():
                return "skipped_no_recipient_email"
            recipient_email = user.email
        if not (recipient_email or "").strip():
            return "skipped_no_recipient_email"
        msg = build_message(notification)
        msg["From"] = (eff.get("from_address") or "").strip()
        msg["To"] = recipient_email.strip()
        send_message(eff, msg)
        return "sent"
    except smtplib.SMTPAuthenticationError:
        logger.warning("email delivery failed: SMTP authentication error")
    except smtplib.SMTPException:
        logger.warning("email delivery failed: SMTP error")
    except Exception:
        # Exception strings can contain credentials supplied by the server.
        logger.warning("email delivery failed: connection or configuration error")
    return "failed"
