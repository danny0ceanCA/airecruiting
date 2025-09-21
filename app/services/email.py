import smtplib
from email.message import EmailMessage

from app.core.config import EMAIL_SENDER, SITE_BASE_URL, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER
from app.core.logging import get_logger

logger = get_logger(__name__)

def send_email(
    recipient: str,
    subject: str,
    body: str,
    html_body: str | None = None,
    attachments: list[tuple[str, bytes | str, str]] | None = None,
    track_token: str | None = None,
) -> None:
    """Send an email with optional attachments.

    Raises a RuntimeError if SMTP settings are missing or if sending fails so
    callers can surface the failure to the user."""
    if not SMTP_HOST or not EMAIL_SENDER:
        raise RuntimeError("SMTP configuration is missing")

    try:
        msg = EmailMessage()
        msg["From"] = EMAIL_SENDER
        msg["To"] = recipient
        msg["Subject"] = subject

        text_body = body
        html_part = html_body or body
        if track_token:
            pixel_url = (
                f"{SITE_BASE_URL}/track/open/{track_token}.png"
                if SITE_BASE_URL
                else f"/track/open/{track_token}.png"
            )
            html_part += f"\n<img src=\"{pixel_url}\" width=\"1\" height=\"1\" />"

        msg.set_content(text_body)
        if html_part != text_body:
            msg.add_alternative(html_part, subtype="html")

        if attachments:
            for filename, content, mime in attachments:
                if isinstance(content, str):
                    content = content.encode("utf-8")
                maintype, subtype = mime.split("/", 1)
                msg.add_attachment(
                    content,
                    maintype=maintype,
                    subtype=subtype,
                    filename=filename,
                )

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            if SMTP_USER and SMTP_PASSWORD:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
        logger.info("[email] Sent notification to %s", recipient)
    except Exception as e:
        logger.error("[email] Failed to send email to %s: %s", recipient, e)
        raise
