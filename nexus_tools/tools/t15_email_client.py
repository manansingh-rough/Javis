"""
NEXUS AI v4.0 — Tool 15: Email client (SMTP send + IMAP read).
Hardware: Intel i3 7th Gen · 12GB RAM · Ollama + Groq API

Sends emails via SMTP and reads emails via IMAP with attachment support.
"""

import json
import logging
import time
import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger("nexus.tool.email_client")


def email_client(
    action: str,
    to: Optional[str] = None,
    subject: str = "",
    body: str = "",
    smtp_server: str = "smtp.gmail.com",
    smtp_port: int = 587,
    imap_server: str = "imap.gmail.com",
    imap_port: int = 993,
    username: Optional[str] = None,
    password: Optional[str] = None,
    attachment_paths: Optional[List[str]] = None,
    max_emails: int = 10,
    folder: str = "INBOX",
) -> str:
    """
    Send and read emails via SMTP/IMAP.
    
    Use this tool when: The user asks to send an email, check their inbox,
    read recent emails, or send an email with attachments.
    
    Args:
        action: "send" or "read"
        to: Recipient email address (for "send").
        subject: Email subject line.
        body: Email body text.
        smtp_server: SMTP server hostname.
        smtp_port: SMTP server port (587 for TLS).
        imap_server: IMAP server hostname.
        imap_port: IMAP server port (993 for SSL).
        username: Email account username (usually full email).
        password: Email account password or app password.
        attachment_paths: List of file paths to attach.
        max_emails: Maximum emails to fetch (for "read").
        folder: IMAP folder to read from.
    
    Returns:
        JSON string with keys:
          - success (bool): Whether the operation succeeded.
          - result (any): Confirmation or list of emails.
          - error (str or null): Error message if failed.
    """
    start = time.perf_counter()
    
    try:
        if action == "send":
            return _send_email(to, subject, body, smtp_server, smtp_port, username, password, attachment_paths)
        elif action == "read":
            return _read_emails(imap_server, imap_port, username, password, max_emails, folder)
        else:
            return json.dumps({
                "success": False, "result": None,
                "error": f"Unknown action: '{action}'. Valid: send, read"
            })
    except Exception as e:
        logger.error(f"email_client error: {e}", exc_info=True)
        return json.dumps({
            "success": False, "result": None,
            "error": f"{type(e).__name__}: {e}"
        })


def _send_email(to, subject, body, smtp_server, smtp_port, username, password, attachment_paths):
    """Send an email via SMTP."""
    if not to or not username or not password:
        return json.dumps({
            "success": False, "result": None,
            "error": "Recipient (to), username, and password are required"
        })
    
    msg = MIMEMultipart()
    msg["From"] = username
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    
    # Attach files
    if attachment_paths:
        for path in attachment_paths:
            try:
                p = Path(path)
                if p.exists():
                    with open(p, "rb") as f:
                        part = MIMEBase("application", "octet-stream")
                        part.set_payload(f.read())
                        encoders.encode_base64(part)
                        part.add_header("Content-Disposition", f"attachment; filename={p.name}")
                        msg.attach(part)
            except Exception as e:
                logger.warning(f"Failed to attach {path}: {e}")
    
    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg)
        
        return json.dumps({
            "success": True,
            "result": f"Email sent to {to}",
            "error": None,
            "metadata": {"to": to, "subject": subject, "attachments": len(attachment_paths or [])}
        })
    except smtplib.SMTPAuthenticationError:
        return json.dumps({
            "success": False, "result": None,
            "error": "SMTP authentication failed. Check username/password. For Gmail, use an App Password."
        })
    except smtplib.SMTPException as e:
        return json.dumps({
            "success": False, "result": None,
            "error": f"SMTP error: {e}"
        })


def _read_emails(imap_server, imap_port, username, password, max_emails, folder):
    """Read emails from IMAP inbox."""
    if not username or not password:
        return json.dumps({
            "success": False, "result": None,
            "error": "Username and password are required"
        })
    
    max_emails = min(max(max_emails, 1), 50)
    
    try:
        with imaplib.IMAP4_SSL(imap_server, imap_port, timeout=30) as mail:
            mail.login(username, password)
            mail.select(folder)
            
            status, messages = mail.search(None, "ALL")
            if status != "OK":
                return json.dumps({"success": False, "result": None, "error": "No emails found"})
            
            email_ids = messages[0].split()
            # Get the most recent emails
            recent_ids = email_ids[-max_emails:]
            
            emails_list = []
            for eid in reversed(recent_ids):
                status, msg_data = mail.fetch(eid, "(RFC822)")
                if status != "OK":
                    continue
                
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                email_dict = {
                    "id": eid.decode(),
                    "from": msg.get("From", ""),
                    "to": msg.get("To", ""),
                    "subject": msg.get("Subject", ""),
                    "date": msg.get("Date", ""),
                    "body": "",
                }
                
                # Extract body
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            try:
                                email_dict["body"] = part.get_payload(decode=True).decode("utf-8", errors="replace")[:1000]
                            except Exception:
                                pass
                            break
                else:
                    try:
                        email_dict["body"] = msg.get_payload(decode=True).decode("utf-8", errors="replace")[:1000]
                    except Exception:
                        pass
                
                emails_list.append(email_dict)
            
            return json.dumps({
                "success": True,
                "result": emails_list,
                "error": None,
                "metadata": {"count": len(emails_list), "folder": folder}
            })
    
    except imaplib.IMAP4.error as e:
        return json.dumps({
            "success": False, "result": None,
            "error": f"IMAP error: {e}"
        })